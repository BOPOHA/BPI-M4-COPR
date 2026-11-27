"""Run native CMD18 and existing CMD25 through the actual controller code."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.test_sd_fast import fast_harness

DRIVER = Path(__file__).resolve().parents[1] / 'src/linux/mmc'


def harness(source):
    code = fast_harness(source)
    code = code.replace('static bool write_enable=true, native_write=true;', '''
static bool write_enable=true, native_write=true, native_read=true;
static char *read_cid="413432534433324730002a677401128b";
static unsigned long long read_capacity=108;
#define length len
#define for_each_sg(list,sg,count,n) for ((n)=0,(sg)=(list);(n)<(count);(n)++,(sg)++)
''')
    code = code.replace('static int scenario;', 'static unsigned char *read_caller;\nstatic int scenario;')
    code = code.replace('    if (op==25) {', '''
    if (op==18) {
        assert(native_read && state==4 && v==0x8d && regs[CFG2]==1 && regs[CFG3]==0);
        assert((regs[CFG1]&3)==expected_bus_bits);
        assert(readl(regs+DMA3)==3 && readl(regs+DMA2)==active_data->blocks);
        memcpy(buffer,media,active_data->blocks*512);
        state=(scenario==43 || scenario==44 || scenario==61) ? 4 : 5;
        response(0xffffffff); /* AUTO_READ1 command bytes are not R1. */
        if (scenario!=52) writel(2,regs+DMA3);
        if (scenario==46) regs[ST1]=0x40;
        if (scenario==47) regs[ST1]=0x80;
        if (scenario==48) regs[ST1]=2;
        if (scenario==49) regs[ST2]=1;
        if (scenario==50) regs[TRANS]=0x10;
        if (scenario==51) regs[TRANS]=0;
    } else if (op==13 && scenario>=42) {
        assert(!active_data->bytes_xfered && !(readl(regs+DMA3)&1));
        for (unsigned int j=0;j<active_data->blocks*512;j++) assert(read_caller[j]==0xa5);
        assert(!memcmp(buffer,media,active_data->blocks*512));
        assert(regs[CFG3]==0);
        polls++;
        if (state==5) {
            if (scenario==45 && polls==3) {state=4; response(0x900);}
            else response(5<<9);
        } else response(0x900);
        if ((scenario==44 && polls==1) || scenario==61) response(4<<9);
        if (scenario==53 || (scenario==58 && polls>1)) response(0x00400900);
        if (scenario==54 || (scenario==82 && polls>1)) regs[ST1]=0x80;
        if (scenario==55) regs[TRANS]=0x10;
        if (scenario==56) response(6<<9);
        if (scenario==59 && polls>1) response(7<<9);
        if (scenario==81 || (scenario==89 && polls>1)) regs[ST2]=2;
        if (scenario==88) regs[ST1]=2;
    } else if (op==12 && scenario>=42) {
        assert(state==5 && regs[CFG2]==0x7c && regs[CFG3]==0 && v==0x88);
        assert(!(readl(regs+DMA3)&1) && !active_data->bytes_xfered);
        for (unsigned int j=0;j<active_data->blocks*512;j++) assert(read_caller[j]==0xa5);
        assert(!memcmp(buffer,media,active_data->blocks*512));
        state=(scenario==45 || scenario==60) ? 5 : 4;
        response(0xffffffff); /* CMD12 has no CPU R1; CMD13 checks completion. */
        if (scenario==57) regs[TRANS]=0x10;
    } else if (op==25) {''')
    code = code.replace('    struct scatterlist parts[2];', '    struct scatterlist parts[2], pages[16];')
    code = code.replace('    active_data=&data;', '    read_caller=input;\n    active_data=&data;')
    code = code.replace('    switch (scenario) {', '''
    if (scenario>=42) {
        data.flags=MMC_DATA_READ; cmd.opcode=18;
        memset(input,0xa5,sizeof(input));
        for (unsigned int j=0;j<sizeof(media);j++) media[j]=(j*31+7)%251;
        host.bus_bits=expected_bus_bits=1;
    }
    switch (scenario) {''')
    code = code.replace('    default: abort();', '''
    case 42: case 43: case 44: case 45: case 46: case 47: case 48:
    case 49: case 50: case 51: case 52: case 53: case 54: case 55:
    case 56: case 57: case 58: case 59: case 60: case 61: case 81:
    case 82: case 88: case 89: break;
    case 62: card.raw_cid[0]++; break;
    case 63: read_capacity++; break;
    case 64: cmd.arg=108; break;
    case 65: cmd.arg=107; break;
    case 66: data.blocks=129; break;
    case 67: data.blocks=0; break;
    case 68: data.flags|=MMC_DATA_WRITE; break;
    case 69: cmd.data=NULL; break;
    case 70: mrq.sbc=&sbc; break;
    case 71: sg.len=4095; break;
    case 72: mmc.card=NULL; break;
    case 73: card.blockaddr=false; break;
    case 74: host.failed=true; break;
    case 75:
        native_read=false;
        for (unsigned int j=0;j<sizeof(media);j++) media[j]=((j%512)*31+7)%251;
        break;
    case 76: case 77:
        card.csd.capacity=read_capacity=228; data.blocks=128; sg.len=SD_BUFFER_BYTES;
        if (scenario==77) {
            parts[0]=(struct scatterlist){input,32768};
            parts[1]=(struct scatterlist){input+32768,32768};
            data.sg=parts; data.sg_len=2;
        }
        break;
    case 78: data.blocks=1; break;
    case 79: mrq.stop=NULL; break;
    case 80: write_enable=native_write=false; break;
    case 83:
        card.csd.capacity=read_capacity=228; data.blocks=128;
        for (unsigned int j=0;j<16;j++) pages[j]=(struct scatterlist){input+j*4096,4096};
        data.sg=pages; data.sg_len=16;
        break;
    case 84: cmd.arg=0xffffffffU; break;
    case 85: data.sg=NULL; break;
    case 86: data.sg_len=0; break;
    case 87: data.blksz=1024; break;
    case 90: read_cid=NULL; break;
    case 91: read_capacity=0; break;
    default: abort();''')
    code = code.replace('    bool success=', '''
    if (scenario>=42) {
        bool ok=scenario==42 || scenario==43 || scenario==44 || scenario==45 ||
            (scenario>=75 && scenario<=80) || scenario==83;
        if (ok) {
            assert(!cmd.error && !data.error && (!mrq.stop || !stop.error));
            assert(data.bytes_xfered==data.blocks*512 && !host.failed);
            assert(!memcmp(input,media,data.bytes_xfered));
            if (scenario==75) {assert(calls==8 && !polls);}
            else {
                assert(sd_write_status_ready(cmd.resp[0]));
                assert(sequence[0]==18);
                if (scenario==43) assert(calls==2);
                else if (scenario==44) assert(calls==3);
                else if (scenario==45) assert(calls==5);
                else assert(calls==4);
            }
        } else {
            assert(cmd.error && data.error && !data.bytes_xfered);
            for (unsigned int j=0;j<sizeof(input);j++) assert(input[j]==0xa5);
            if ((scenario>=46 && scenario<=61) || scenario==81 || scenario==82 || scenario==88 || scenario==89) {
                assert(host.failed);
                if (scenario<=52) assert(calls==1 && !polls);
                unsigned int before=calls; u8 saved[SD_BUFFER_BYTES]; memcpy(saved,buffer,sizeof(saved));
                host.mrq=&mrq; sd_work(&host.work);
                assert(calls==before && !data.bytes_xfered && !memcmp(saved,buffer,sizeof(saved)));
                for (unsigned int j=0;j<sizeof(input);j++) assert(input[j]==0xa5);
            } else assert(!calls);
        }
        return 0;
    }
    bool success=''')
    return code


class NativeReadTests(unittest.TestCase):
    def test_actual_native_read_completion_faults_and_existing_writes(self):
        program = harness((DRIVER/'bpi-m4-sd-cmd18.c').read_text())
        with tempfile.TemporaryDirectory(prefix='bpi-cmd18-') as directory:
            p=Path(directory)
            (p/'test.c').write_text(program)
            subprocess.run(['cc','-Wall','-Wextra','-Werror','-I',str(DRIVER),str(p/'test.c'),'-o',str(p/'test')],check=True)
            for scenario in range(92):
                with self.subTest(scenario=scenario):
                    subprocess.run([str(p/'test'),str(scenario)],check=True)
