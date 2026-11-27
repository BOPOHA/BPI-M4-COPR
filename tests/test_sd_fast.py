"""Run four-bit/64 KiB commands and fault handling against the actual driver."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from tests.test_sd_cmd25 import HARNESS

ROOT = Path(__file__).resolve().parents[1]


def fast_harness(source):
    registers = source[source.index('#define DMA1'):source.index('struct sd_probe {')]
    metrics = source[source.index('enum sd_metric {'):source.index('#ifdef BPI_M4_SD_PROFILE')]
    gate = source[source.index('static bool sd_write_permitted'):source.index('static inline u64 sd_now')]
    commands = source[source.index('/* Vendor asm/io.h'):source.index('static void sd_request(')]
    ios = source[source.index('static void sd_ios('):source.index('static int sd_ro(')]
    harness = HARNESS.replace('#define SD_BUFFER_BYTES PAGE_SIZE', '#define SD_BUFFER_BYTES (64 * 1024)')
    harness = harness.replace('unsigned int data_clock; bool failed;', 'unsigned int data_clock; u8 bus_bits; bool failed;')
    harness = harness.replace('struct mmc_host { struct mmc_card *card; };', '''
struct mmc_host { struct mmc_card *card; void *private; unsigned int actual_clock; };
struct mmc_ios { unsigned int clock, timing, bus_width; };
#define MMC_TIMING_SD_HS 2
#define MMC_BUS_WIDTH_4 2
#define mmc_priv(h) ((h)->private)
''')
    harness = harness.replace('buffer[PAGE_SIZE], media[PAGE_SIZE]', 'buffer[SD_BUFFER_BYTES], media[SD_BUFFER_BYTES]')
    start = harness.index('static unsigned int sg_copy_to_buffer(')
    end = harness.index('static u32 get_unaligned_be32(', start)
    harness = harness[:start] + '''
static unsigned int sg_copy_to_buffer(struct scatterlist *sg, unsigned int count, void *p, unsigned int n) {
    unsigned int copied=0;
    for (unsigned int i=0;i<count && copied<n;i++) {
        unsigned int length=sg[i].len<n-copied ? sg[i].len : n-copied;
        memcpy((u8 *)p+copied,sg[i].ptr,length); copied+=length;
    }
    return copied;
}
static unsigned int sg_copy_from_buffer(struct scatterlist *sg, unsigned int count, const void *p, unsigned int n) {
    unsigned int copied=0;
    for (unsigned int i=0;i<count && copied<n;i++) {
        unsigned int length=sg[i].len<n-copied ? sg[i].len : n-copied;
        memcpy(sg[i].ptr,(const u8 *)p+copied,length); copied+=length;
    }
    return copied;
}
''' + harness[end:]
    harness = harness.replace('static int scenario;', 'static int scenario; static unsigned int expected_bus_bits;')
    harness = harness.replace('assert(state==4 && v==0x89', 'assert((regs[CFG1]&3)==expected_bus_bits);\n        assert(state==4 && v==0x89')
    harness = harness.replace('} else if (op==24) {', '''} else if (op==17) {
        memcpy(buffer,media,512); response(0x900); writel(0,regs+DMA3);
        if (scenario==38) regs[ST1]=0x40;
        if (scenario==39) regs[ST2]=2;
        if (scenario==40) response(0x00400900);
    } else if (op==24) {''')
    harness = harness.replace('unsigned char input[PAGE_SIZE];', 'unsigned char input[SD_BUFFER_BYTES];')
    harness = harness.replace('i<PAGE_SIZE;i++) input', 'i<SD_BUFFER_BYTES;i++) input')
    harness = harness.replace('    active_data=&data;', '    struct scatterlist parts[2];\n    mmc.private=&host;\n    active_data=&data;')
    harness = harness.replace('    default: abort();', '''    case 34: case 35: case 37:
        scratch_sectors=128; card.csd.capacity=228; data.blocks=scenario==35 ? 129 : 128;
        sg.len=SD_BUFFER_BYTES; host.bus_bits=expected_bus_bits=1;
        if (scenario==37) {
            parts[0]=(struct scatterlist){input,32768};
            parts[1]=(struct scatterlist){input+32768,32768};
            data.sg=parts; data.sg_len=2;
        }
        break;
    case 36: {
        struct mmc_ios ios={50000000,MMC_TIMING_SD_HS,MMC_BUS_WIDTH_4};
        sd_ios(&mmc,&ios); expected_bus_bits=1;
        assert(host.bus_bits==1 && regs[CFG1]==0x11 && mmc.actual_clock==50000000);
        break;
    }
    case 38: case 39: case 40: case 41:
        data.flags=MMC_DATA_READ; data.blocks=1; cmd.opcode=17; cmd.retries=0;
        mrq.stop=NULL; memset(input,0xa5,sizeof(input)); memset(media,0x5a,512);
        break;
    default: abort();''')
    harness = harness.replace('scenario==30 || scenario==32;', 'scenario==30 || scenario==32 || scenario==34 || scenario==36 || scenario==37;')
    harness = harness.replace('    if (scenario==29) {', '''    if (scenario==41) {
        assert(!cmd.error && !data.error && data.bytes_xfered==512 && calls==1);
        assert(!memcmp(input,media,512));
    } else if (scenario==29) {''')
    harness = harness.replace('(scenario>=10 && scenario<=20) || scenario==31 || scenario==33',
                              '(scenario>=10 && scenario<=20) || scenario==31 || scenario==33 || (scenario>=38 && scenario<=40)')
    harness = harness.replace('            unsigned int previous=calls;', '''            if (scenario>=38) for (unsigned int j=0;j<512;j++) assert(input[j]==0xa5);
            unsigned int previous=calls;''')
    return harness.replace('REGISTERS', registers).replace('METRICS', metrics).replace('ACTUAL', gate+commands+ios)


