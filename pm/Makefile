ifndef PS5_PAYLOAD_SDK
$(error PS5_PAYLOAD_SDK must point to SDK v0.45)
endif
include $(PS5_PAYLOAD_SDK)/toolchain/prospero.mk
CFLAGS += -O2 -Wall -Wextra -Werror -std=gnu11
TARGET ?= ../dist/pm-autoupdate.elf
SEED := ../build/pm-seed/nanodns.elf
SOURCES := src/main.c src/json.c src/http.c third_party/sha256.c bootstrap/seed.S

.PHONY: all verify-seed
all: $(TARGET)

generated_defaults.h: generate_defaults.py
	python3 generate_defaults.py

verify-seed:
	python3 bootstrap/fetch.py $(SEED)

$(SEED):
	python3 bootstrap/fetch.py $@

$(TARGET): $(SOURCES) src/json.h src/http.h third_party/sha256.h generated_defaults.h $(SEED) | verify-seed
	mkdir -p $(dir $(TARGET))
	$(CC) $(CFLAGS) -I. -Isrc -Ithird_party -o $@ $(SOURCES)
