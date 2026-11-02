// Validate the entire stopped configuration before enabling capture.
module urx2_config_guard(input wire [31:0] cfg[0:283],output reg valid);
    integer i,w;
    always @* begin
        valid=cfg[0]>=1 && cfg[0]<=512 && cfg[2]>=1 && cfg[2]<=4 && cfg[2]<=cfg[0] &&
              cfg[3]<=4 && cfg[7]<=1 && cfg[14]>=1 && cfg[14]<=16 && cfg[15]<=255 && {cfg[13],cfg[12]}!=0;
        w=cfg[3]==4?4:cfg[3]==3?2:1;
        if(cfg[3]!=0 && !(cfg[4]<cfg[5] && cfg[5]<=cfg[0] && cfg[6]+w<=cfg[0]))valid=0;
        if(cfg[8]!=255 && !(cfg[8]<cfg[14] && cfg[9]>=1 && cfg[9]<=32 && !cfg[16+cfg[8][3:0]*12][14]))valid=0;
        if(cfg[10]!=255 && !(cfg[10]<cfg[14] && cfg[11]>=1 && cfg[11]<=32 && !cfg[16+cfg[10][3:0]*12][14]))valid=0;
        for(i=0;i<16;i=i+1)if(i<cfg[14])begin
            if(!(cfg[16+i*12][12:10]==1 || cfg[16+i*12][12:10]==2 || cfg[16+i*12][12:10]==4))valid=0;
            if(cfg[16+i*12][9:0]+cfg[16+i*12][12:10]>cfg[0])valid=0;
            if(cfg[22+i*12]!=255 && cfg[22+i*12]>=cfg[14])valid=0;
        end
        for(i=0;i<8;i=i+1)if(cfg[15][i])begin
            if(cfg[208+i*8][7:0]>=cfg[14] || cfg[208+i*8][11:8]<1 || cfg[208+i*8][11:8]>4 ||
               cfg[208+i*8][15:12]>5)valid=0;
        end
        for(i=0;i<4;i=i+1)if(cfg[274+i*3]>4 || cfg[272+i*3]+cfg[274+i*3]>cfg[0])valid=0;
    end
endmodule
