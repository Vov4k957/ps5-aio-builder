ifndef PS5_PAYLOAD_SDK
$(error PS5_PAYLOAD_SDK must point to SDK v0.45)
endif
include $(PS5_PAYLOAD_SDK)/toolchain/prospero.mk
CFLAGS += -O2 -Wall -Wextra -Werror -std=gnu11
TARGET ?= ../dist/pm-autoupdate.elf

.PHONY: all
all: $(TARGET)

generated_defaults.h: generate_defaults.py ../config/payloads.json
	python3 generate_defaults.py

$(TARGET): src/main.c src/json.c src/json.h src/http.c src/http.h generated_defaults.h
	mkdir -p $(dir $(TARGET))
	$(CC) $(CFLAGS) -I. -Isrc -o $@ src/main.c src/json.c src/http.c
