TOOLCHAIN_PREFIX ?= riscv64-elf
CC := $(TOOLCHAIN_PREFIX)-gcc
OBJCOPY := $(TOOLCHAIN_PREFIX)-objcopy
OBJDUMP := $(TOOLCHAIN_PREFIX)-objdump

SUITE ?= dirtygen

ifeq ($(SUITE),phase1)
BUILD_DIR ?= build/phase1
IMAGE_NAME := dirtygen_phase1
SUITE_CPPFLAGS := -DDIRTYGEN_PHASE1
C_SOURCES := \
  src/phase1.c \
  src/page_table.c
else ifeq ($(SUITE),phase6)
BUILD_DIR ?= build/phase6
IMAGE_NAME := dirtygen_phase6
SUITE_CPPFLAGS := -DDIRTYGEN_PHASE6
C_SOURCES := \
  src/phase6.c \
  src/page_table.c
else ifeq ($(SUITE),perf)
BUILD_DIR ?= build/perf
IMAGE_NAME := dirtygen_perf
PERF_CONFIG_MASK ?= 0xffffffff
SUITE_CPPFLAGS := -DDIRTYGEN_PERF \
                  -DDIRTYGEN_PERF_CONFIG_MASK=$(PERF_CONFIG_MASK)
C_SOURCES := \
  src/dirtygen_perf.c \
  src/dirty_log_check.c \
  src/page_table.c
else ifeq ($(SUITE),dirtygen)
BUILD_DIR ?= build
IMAGE_NAME := dirtygen
C_SOURCES := \
  src/dirtygen.c \
  src/dirty_log_check.c \
  src/dirty_log_random.c \
  src/page_table.c
else
$(error SUITE must be dirtygen, phase1, phase6, or perf)
endif

CASE_FIRST ?= 0
CASE_LIMIT ?= 32

ARCH_FLAGS := -march=rv64i_zicsr -mabi=lp64 -mcmodel=medany
CPPFLAGS := -Iinclude -Isrc \
            -DDIRTYGEN_CASE_FIRST=$(CASE_FIRST) \
            -DDIRTYGEN_CASE_LIMIT=$(CASE_LIMIT) \
            $(SUITE_CPPFLAGS)
COMMON_FLAGS := $(ARCH_FLAGS) -Os -ffreestanding -fno-builtin \
                -ffunction-sections -fdata-sections
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror \
          -Wno-missing-field-initializers
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := $(ARCH_FLAGS) -nostdlib -nostartfiles -static \
           -Wl,-T,linker.ld,-Map,$(BUILD_DIR)/dirtygen.map,--gc-sections

ASM_SOURCES := src/startup.S
OBJECTS := $(patsubst src/%.c,$(BUILD_DIR)/%.o,$(C_SOURCES)) \
           $(patsubst src/%.S,$(BUILD_DIR)/%.o,$(ASM_SOURCES))
DEPS := $(OBJECTS:.o=.d)

.PHONY: all phase1 phase6 clean report test-report test-phase1-report \
        test-phase6-report

all: $(BUILD_DIR)/$(IMAGE_NAME).elf $(BUILD_DIR)/$(IMAGE_NAME).bin \
     $(BUILD_DIR)/$(IMAGE_NAME).asm

phase1:
	$(MAKE) SUITE=phase1 BUILD_DIR=build/phase1 all

phase6:
	$(MAKE) SUITE=phase6 BUILD_DIR=build/phase6 all

perf:
	$(MAKE) SUITE=perf BUILD_DIR=build/perf \
		PERF_CONFIG_MASK=0xffffffff all

perf-rvls-smoke:
	$(MAKE) SUITE=perf BUILD_DIR=build/perf-rvls-smoke \
		PERF_CONFIG_MASK=0x0f0000f0 all

$(BUILD_DIR)/$(IMAGE_NAME).elf: $(OBJECTS) linker.ld | $(BUILD_DIR)
	$(CC) $(OBJECTS) $(LDFLAGS) -lgcc -o $@

$(BUILD_DIR)/$(IMAGE_NAME).bin: $(BUILD_DIR)/$(IMAGE_NAME).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD_DIR)/$(IMAGE_NAME).asm: $(BUILD_DIR)/$(IMAGE_NAME).elf
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

test-phase1-report:
	python3 -m unittest -v tests/test_phase1_report.py

test-phase6-report:
	python3 -m unittest -v tests/test_phase6_report.py

clean:
	rm -rf $(BUILD_DIR)

-include $(DEPS)
