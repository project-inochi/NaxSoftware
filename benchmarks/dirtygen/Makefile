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
ifneq ($(strip $(PERF_ISOLATED_CONFIG)),)
ifneq ($(strip $(PERF_SCHEDULE_ID)),)
$(error PERF_ISOLATED_CONFIG and PERF_SCHEDULE_ID are mutually exclusive)
endif
SUITE_CPPFLAGS += -DDIRTYGEN_PERF_ISOLATED
endif
ifneq ($(strip $(PERF_SCHEDULE_ID)),)
SUITE_CPPFLAGS += -DDIRTYGEN_PERF_SCHEDULE_ID=$(PERF_SCHEDULE_ID)
endif
C_SOURCES := \
  src/dirtygen_perf.c \
  src/dirty_log_check.c \
  src/page_table.c
ifneq ($(strip $(PERF_ISOLATED_CONFIG)),)
C_SOURCES += src/dirtygen_perf_selection.c
endif
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

.PHONY: all phase1 phase6 perf perf-rvls-smoke perf-isolated clean report \
        perf-report \
        test-report test-phase1-report test-phase6-report \
        test-perf-report test-perf-campaign test-perf-compare test-perf

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

perf-isolated:
	@test -n "$(PERF_ISOLATED_CONFIG)" || { \
		echo "usage: make perf-isolated PERF_ISOLATED_CONFIG=0..31"; exit 2; }
	$(MAKE) SUITE=perf \
		BUILD_DIR=build/perf-isolated-c$(PERF_ISOLATED_CONFIG) \
		PERF_ISOLATED_CONFIG=$(PERF_ISOLATED_CONFIG) all

$(BUILD_DIR)/$(IMAGE_NAME).elf: $(OBJECTS) linker.ld | $(BUILD_DIR)
	$(CC) $(OBJECTS) $(LDFLAGS) -lgcc -o $@

$(BUILD_DIR)/$(IMAGE_NAME).bin: $(BUILD_DIR)/$(IMAGE_NAME).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD_DIR)/$(IMAGE_NAME).asm: $(BUILD_DIR)/$(IMAGE_NAME).elf
	$(OBJDUMP) -S -d $< > $@

$(BUILD_DIR)/%.o: src/%.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@

ifneq ($(strip $(PERF_ISOLATED_CONFIG)),)
$(BUILD_DIR)/dirtygen_perf_selection.o: src/dirtygen_perf_selection.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) \
		-DDIRTYGEN_PERF_ISOLATED_CONFIG=$(PERF_ISOLATED_CONFIG) \
		-MMD -MP -c $< -o $@
endif

$(BUILD_DIR)/%.o: src/%.S | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR):
	mkdir -p $@

report:
	@test -n "$(LOG)" || { echo "usage: make report LOG=/path/to/log"; exit 2; }
	python3 tools/dirtygen_report.py "$(LOG)" --format table

perf-report:
	@test -n "$(LOG)" || { echo "usage: make perf-report LOG=/path/to/log PERF_SUITE=full|smoke|sensitivity [PERF_SCHEDULE=legacy|S0|S1|S2|S3]"; exit 2; }
	@test -n "$(PERF_SUITE)" || { echo "PERF_SUITE must be full, smoke, or sensitivity"; exit 2; }
	python3 tools/dirtygen_perf_report.py "$(LOG)" \
		--suite "$(PERF_SUITE)" \
		--schedule-id "$(or $(PERF_SCHEDULE),legacy)" --format table

test-report:
	python3 -m unittest -v tests/test_dirtygen_report.py

test-phase1-report:
	python3 -m unittest -v tests/test_phase1_report.py

test-phase6-report:
	python3 -m unittest -v tests/test_phase6_report.py

test-perf-report:
	python3 -m unittest -v tests/test_dirtygen_perf_report.py

test-perf-campaign:
	python3 -m unittest -v tests/test_dirtygen_perf_campaign.py

test-perf-compare:
	python3 -m unittest -v tests/test_dirtygen_perf_compare.py

test-perf: test-perf-report test-perf-campaign test-perf-compare

clean:
	rm -rf $(BUILD_DIR)

-include $(DEPS)
