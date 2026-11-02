"""Bounded receive pump: disk/UI work cannot hold the hardware FIFO reader."""
import queue
import threading
import time
from .decoder import ByteChunk


class BufferedTransport:
    """One hardware owner; ordered chunks retain their observation time and state.

    A full host queue stops acquisition and reports an error. It never silently
    drops a chunk or overwrites evidence. Replay transports use their original
    deterministic path and do not pass through this pump.
    """
    hardware_accessed = True

    def __init__(self, transport, seconds, capacity=1024):
        if capacity < 1:
            raise ValueError('Receive buffer capacity must be positive')
        self.transport = transport
        self.seconds = seconds
        self.queue = queue.Queue(maxsize=capacity)
        self.tail = []
        self.drain_limit = capacity + 34
        self.requested = threading.Event()
        self.done = threading.Event()
        self.thread = None
        self.error = None
        self.stopped_ticks = None
        self.tick = None
        self.offset = 0
        self.state = transport.registers()
        self.eof = False
        self.provenance = dict(transport.provenance)
        self.provenance['receive_buffer_chunks'] = capacity
        self.provenance['receive_buffer_chunk_bytes'] = 256
        self.detection_source = getattr(transport, 'detection_source', 'software')
        self.high_water = 0

    def registers(self):
        if self.thread is None:
            return self.transport.registers()
        state = dict(self.final_state if self.done.is_set() else self.state)
        state.update(host_buffer_high_water=self.high_water,
                     host_buffer_capacity=self.queue.maxsize,
                     host_buffer_error=str(self.error) if self.error else None)
        return state

    def now_ticks(self):
        return self.transport.now_ticks() if self.tick is None else self.tick

    def start(self):
        self.tick = self.transport.start()
        self.thread = threading.Thread(target=self._pump, name='URX-receive', daemon=True)
        self.thread.start()
        return self.tick

    def _pump(self):
        deadline = time.monotonic() + self.seconds
        heartbeat = time.monotonic()
        pending = None
        def packet(item):
            chunk = ByteChunk(item['data'], item['ticks'], item['offset'], item['state'])
            chunk.hardware_events = item['events']
            return chunk, item['sampled']
        def flush():
            nonlocal pending, heartbeat
            item = packet(pending)
            pending = None
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                self.tail.append(item)
                raise RuntimeError('Host receive buffer full; acquisition stopped without overwriting queued bytes')
            self.high_water = max(self.high_water, self.queue.qsize())
            heartbeat = time.monotonic()
        try:
            while not self.requested.is_set() and time.monotonic() < deadline:
                chunk = self.transport.read()
                sampled = self.transport.now_ticks()
                now = time.monotonic()
                # A UART poll can return just one byte. Coalesce by bytes/time,
                # otherwise tiny fragments exhaust a chunk-count queue while
                # its intended byte capacity is still mostly unused.
                if pending is not None and len(pending['data'])+len(chunk.data)>256:
                    flush()
                if pending is None:
                    pending = dict(data=bytearray(), ticks=[], offset=chunk.raw_offset,
                                   state=chunk.state, events=[], sampled=sampled)
                if pending['offset']+len(pending['data']) != chunk.raw_offset:
                    raise ValueError('Receive pump raw byte discontinuity')
                pending['data'].extend(chunk.data)
                pending['ticks'].extend(chunk.ticks)
                pending['events'].extend(getattr(chunk, 'hardware_events', []))
                pending['state'] = chunk.state
                pending['sampled'] = sampled
                if len(pending['data'])>=256 or now-heartbeat >= .05:
                    flush()
                if not chunk.data:
                    time.sleep(.001)
        except BaseException as exc:
            self.error = exc
        finally:
            try:
                if pending is not None and (pending['data'] or pending['events']):
                    self.tail.append(packet(pending))
                self.transport.stop()
                self.stopped_ticks = getattr(self.transport, 'stopped_ticks', None)
                if self.stopped_ticks is None:
                    self.stopped_ticks = self.transport.now_ticks()
                for _ in range(32):
                    chunk = self.transport.read()
                    sampled = self.stopped_ticks
                    if chunk.data or getattr(chunk, 'hardware_events', []):
                        self.tail.append((chunk, sampled))
                    if not chunk.data:
                        break
            except BaseException as exc:
                self.error = self.error or exc
            try:
                self.final_state = self.transport.registers()
            except BaseException as exc:
                self.error = self.error or exc
                self.final_state = dict(self.state)
            self.done.set()

    def read(self, maximum=256):
        while True:
            try:
                item = self.queue.get(timeout=.02)
                break
            except queue.Empty:
                if not self.done.is_set():
                    continue
                # The producer may have queued its last item between timeout
                # and publishing done; preserve FIFO order before the tail.
                try:
                    item = self.queue.get_nowait()
                    break
                except queue.Empty:
                    pass
                if self.tail:
                    item = self.tail.pop(0)
                    break
                self.eof = True
                self.tick = self.stopped_ticks if self.stopped_ticks is not None else self.tick
                self.state = dict(self.final_state)
                if self.error:
                    raise RuntimeError('Receive pump: ' + str(self.error))
                return ByteChunk(b'', [], self.offset, self.state)
        chunk, self.tick = item
        self.state = dict(chunk.state)
        self.offset = chunk.raw_offset + len(chunk.data)
        return chunk

    def stop(self):
        self.requested.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('Receive pump did not stop; preserve its buffers')

    def close(self):
        self.stop()
        self.transport.close()
