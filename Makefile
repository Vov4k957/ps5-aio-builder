# PS5 Payload SDK required for a real console ELF.
ifndef PS5_PAYLOAD_SDK
$(error PS5_PAYLOAD_SDK must point to the installed SDK)
endif
include $(PS5_PAYLOAD_SDK)/toolchain/prospero.mk

PROFILE ?= standard
TARGET := dist/ps5-aio-$(PROFILE).elf
CFLAGS += -Wall -Wextra -O2

.PHONY: all clean
all: $(TARGET)

$(TARGET): src/main.c src/payloads.h build/generated.c build/embedded.S
	@mkdir -p dist
	$(CC) $(CFLAGS) -Isrc -o $@ src/main.c build/generated.c build/embedded.S

clean:
	rm -rf build dist
