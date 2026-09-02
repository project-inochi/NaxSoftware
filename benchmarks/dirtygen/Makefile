TOOLCHAIN_PREFIX ?= riscv64-elf
CC := $(TOOLCHAIN_PREFIX)-gcc
OBJCOPY := $(TOOLCHAIN_PREFIX)-objcopy
OBJDUMP := $(TOOLCHAIN_PREFIX)-objdump

BUILD_DIR ?= build
CASE_FIRST ?= 0
CASE_LIMIT ?= 32

ARCH_FLAGS := -march=rv64i_zicsr -mabi=lp64 -mcmodel=medany
CPPFLAGS := -Iinclude -Isrc \
            -DDIRTYGEN_CASE_FIRST=$(CASE_FIRST) \
            -DDIRTYGEN_CASE_LIMIT=$(CASE_LIMIT)
COMMON_FLAGS := $(ARCH_FLAGS) -Os -ffreestanding -fno-builtin \
                -ffunction-sections -fdata-sections
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror \
          -Wno-missing-field-initializers
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := $(ARCH_FLAGS) -nostdlib -nostartfiles -static \
           -Wl,-T,linker.ld,-Map,$(BUILD_DIR)/dirtygen.map,--gc-sections

C_SOURCES := \
  src/dirtygen.c \
  src/dirty_log_check.c \
  src/dirty_log_random.c \
  src/page_table.c
ASM_SOURCES := src/startup.S
OBJECTS := $(patsubst src/%.c,$(BUILD_DIR)/%.o,$(C_SOURCES)) \
           $(patsubst src/%.S,$(BUILD_DIR)/%.o,$(ASM_SOURCES))
DEPS := $(OBJECTS:.o=.d)

.PHONY: all clean report test-report

all: $(BUILD_DIR)/dirtygen.elf $(BUILD_DIR)/dirtygen.bin \
     $(BUILD_DIR)/dirtygen.asm

$(BUILD_DIR)/dirtygen.elf: $(OBJECTS) linker.ld | $(BUILD_DIR)
	$(CC) $(OBJECTS) $(LDFLAGS) -lgcc -o $@

$(BUILD_DIR)/dirtygen.bin: $(BUILD_DIR)/dirtygen.elf
	$(OBJCOPY) -O binary $< $@

$(BUILD_DIR)/dirtygen.asm: $(BUILD_DIR)/dirtygen.elf
	$(OBJDUMP) -S -d $< > $@

$(BUILD_DIR)/%.o: src/%.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR)/%.o: src/%.S | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR):
	mkdir -p $@

report:
	@test -n "$(LOG)" || { echo "usage: make report LOG=/path/to/log"; exit 2; }
	python3 tools/dirtygen_report.py "$(LOG)" --format table

test-report:
	python3 -m unittest -v tests/test_dirtygen_report.py

clean:
	rm -rf $(BUILD_DIR)

-include $(DEPS)
