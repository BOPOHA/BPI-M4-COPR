"""Exercise the patched copy function's pixels, stride, bounds and failures."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OpaqueScanout(unittest.TestCase):
    def test_real_copy_preserves_rgb_source_padding_and_failure_state(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            shutil.copytree(ROOT/'src/linux/peripherals/drivers/sound/realtek-rtd129x-acpu',
                            work/'sound/realtek-rtd129x-acpu')
            for patch in sorted((ROOT/'src/linux/media').glob('*.patch')):
                subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', patch],
                               cwd=work, check=True, stdout=subprocess.DEVNULL)
            source = (work/'sound/realtek-rtd129x-acpu/acpu-vo.c').read_text()
            actual = source[source.index('static void vo_opaque_line('):
                            source.index('/* Keep user XRGB data intact:')]
            harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#define __iomem
#undef static_assert
#define static_assert(x) _Static_assert(x, #x)
#define VO_SCANOUT_PITCH 64
#define VO_SCANOUT_HEIGHT 3
#define GFP_KERNEL 0
struct iosys_map { void *vaddr; bool is_iomem; };
struct drm_format_conv_state { int unused; };
struct drm_shadow_plane_state {
    struct iosys_map data[1];
    struct drm_format_conv_state fmtcnv_state;
};
struct drm_framebuffer { unsigned int pitches[1]; };
static u64 scratch[8];
static int allocation_fails, transfers;
static void *drm_format_conv_state_reserve(void *s, unsigned int bytes, int gfp) {
    assert(bytes == sizeof(scratch));
    return allocation_fails ? 0 : scratch;
}
static void __iowrite64_copy(void *dst, const void *src, unsigned int count) {
    assert(count == 8); ++transfers; memcpy(dst, src, count * 8);
}
'''
            cases = r'''
int main(void) {
    u32 source[3][20], original[3][20], dest[3*16+2];
    for (unsigned int y=0;y<3;y++)
        for (unsigned int x=0;x<20;x++)
            source[y][x] = (y*91+x*13)*0x01020304U;
    memcpy(original, source, sizeof(source));
    memset(dest, 0x5a, sizeof(dest));
    struct drm_shadow_plane_state shadow={.data={{source, false}}};
    struct drm_framebuffer fb={.pitches={sizeof(source[0])}};
    assert(vo_copy_opaque(dest+1, &shadow, &fb) == 0);
    assert(transfers == 3);
    assert(dest[0] == 0x5a5a5a5a && dest[49] == 0x5a5a5a5a);
    for(unsigned int y=0;y<3;y++)
        for(unsigned int x=0;x<16;x++) {
            assert((dest[1+y*16+x] & 0xffffff) == (source[y][x] & 0xffffff));
            assert((dest[1+y*16+x] >> 24) == 255);
        }
    assert(!memcmp(original, source, sizeof(source)));
    u32 saved[50]; memcpy(saved, dest, sizeof(dest));
    allocation_fails=1;
    assert(vo_copy_opaque(dest+1, &shadow, &fb) == -ENOMEM);
    assert(!memcmp(saved, dest, sizeof(dest)) && transfers == 3);
    shadow.data[0].is_iomem=true;
    assert(vo_copy_opaque(dest+1, &shadow, &fb) == -EINVAL);
    assert(!memcmp(saved, dest, sizeof(dest)) && transfers == 3);
    return 0;
}
'''
            c = work/'copy-test.c'
            c.write_text(harness+actual+cases)
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror', '-o', work/'copy-test', c], check=True)
            subprocess.run([work/'copy-test'], check=True)


if __name__ == '__main__':
    unittest.main()
