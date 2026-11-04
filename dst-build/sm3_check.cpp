#include <cstdint>
#include <iostream>
#include "sm3/sm3_converter.h"
#include "ir/ir_builder.h"
#include "util/util_byte_stream.h"

// Synthetic 52-byte shader; contains no game data.
int main() {
    const uint32_t code[] = {
        0xffff0300, 0x05000051, 0xa00f0000,
        0xbf800000, 0xbf800000, 0xbf800000, 0xbf800000,
        0x01000041, 0xa00f0000,
        0x02000001, 0x800f0800, 0xa0e40000, 0x0000ffff
    };
    static_assert(sizeof(code) == 52);
    dxbc_spv::sm3::Converter::Options options{};
    options.name = "synthetic-texkill-constant";
    options.includeDebugNames = true;
    dxbc_spv::sm3::Converter converter(dxbc_spv::util::ByteReader(code, sizeof(code)), options);
    dxbc_spv::ir::Builder builder;
    if (!converter.convertShader(builder)) return 1;
    std::cout << "PASS: constant-register TEXKILL converted" << std::endl;
    return 0;
}
