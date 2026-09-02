TOOLCHAIN_PREFIX ?= riscv64-elf
CC := $(TOOLCHAIN_PREFIX)-gcc
OBJCOPY := $(TOOLCHAIN_PREFIX)-objcopy
OBJDUMP := $(TOOLCHAIN_PREFIX)-objdump

BUILD_DIR ?= build
CASE_FIRST ?= 0
CASE_LIMIT ?= 23

ARCH_FLAGS := -march=rv64i_zicsr -mabi=lp64 -mcmodel=medany
CPPFLAGS := -Iinclude -Isrc -DPAGEFAULT_CASE_FIRST=$(CASE_FIRST) -DPAGEFAULT_CASE_LIMIT=$(CASE_LIMIT)
COMMON_FLAGS := $(ARCH_FLAGS) -Os -ffreestanding -fno-builtin -ffunction-sections -fdata-sections
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := $(ARCH_FLAGS) -nostdlib -nostartfiles -static -Wl,-T,linker.ld,-Map,$(BUILD_DIR)/pagefaultgen.map,--gc-sections

C_SOURCES := src/page_table.c src/pagefault.c
ASM_SOURCES := src/startup.S src/pagefault.inc.S
OBJECTS := $(patsubst src/%.c,$(BUILD_DIR)/%.o,$(C_SOURCES)) $(patsubst src/%.S,$(BUILD_DIR)/%.o,$(ASM_SOURCES))
DEPS := $(OBJECTS:.o=.d)

.PHONY: all clean report test-report
all: $(BUILD_DIR)/pagefaultgen.elf $(BUILD_DIR)/pagefaultgen.bin $(BUILD_DIR)/pagefaultgen.asm

$(BUILD_DIR)/pagefaultgen.elf: $(OBJECTS) linker.ld | $(BUILD_DIR)
	$(CC) $(OBJECTS) $(LDFLAGS) -lgcc -o $@
$(BUILD_DIR)/pagefaultgen.bin: $(BUILD_DIR)/pagefaultgen.elf
	$(OBJCOPY) -O binary $< $@
$(BUILD_DIR)/pagefaultgen.asm: $(BUILD_DIR)/pagefaultgen.elf
	$(OBJDUMP) -S -d $< > $@
$(BUILD_DIR)/%.o: src/%.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@
$(BUILD_DIR)/%.o: src/%.S | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@
$(BUILD_DIR):
	mkdir -p $@
report:
	@test -n "$(LOG)" || { echo "usage: make report LOG=/path/to/log"; exit 2; }
	python3 tools/pagefault_report.py "$(LOG)" --format table
test-report:
	python3 -m unittest -v tests/test_pagefault_report.py
clean:
	rm -rf $(BUILD_DIR)
-include $(DEPS)
