PROJ_NAME := perf_shdlt
CPU_COUNT ?= 1
SUITE ?= throughput
LOGGER ?= on
ORDER ?= sequential
PHASE ?= single
SCALING ?= strong
HPM ?= off
HPM_COUNTERS ?= 4
HPM_EVENT0 ?= 0x30
HPM_EVENT1 ?= 0x31
HPM_EVENT2 ?= 0x33
HPM_EVENT3 ?= 0x34
RISCV_PATH ?= /usr
RISCV_NAME ?= riscv64-elf
MARCH ?= rv64gc
MABI ?= lp64d

SUITE_ID_throughput := 0
SUITE_ID_latency := 1
SUITE_ID_fault := 2
SUITE_ID_freeze := 3
SUITE_ID_all := 4
ORDER_ID_sequential := 0
ORDER_ID_reverse := 1
ORDER_ID_stride := 2
ORDER_ID_permuted := 3
PHASE_ID_single := 0
PHASE_ID_same := 1
PHASE_ID_phase_shifted := 2
PHASE_ID_opposite := 3
SCALING_ID_strong := 0
SCALING_ID_weak := 1
LOGGER_ID_off := 0
LOGGER_ID_on := 1
HPM_ID_off := 0
HPM_ID_on := 1

SUITE_ID := $(SUITE_ID_$(SUITE))
ORDER_ID := $(ORDER_ID_$(ORDER))
PHASE_ID := $(PHASE_ID_$(PHASE))
SCALING_ID := $(SCALING_ID_$(SCALING))
LOGGER_ID := $(LOGGER_ID_$(LOGGER))
HPM_ID := $(HPM_ID_$(HPM))

ifeq ($(SUITE_ID),)
$(error unknown SUITE '$(SUITE)')
endif
ifeq ($(ORDER_ID),)
$(error unknown ORDER '$(ORDER)')
endif
ifeq ($(PHASE_ID),)
$(error unknown PHASE '$(PHASE)')
endif
ifeq ($(SCALING_ID),)
$(error unknown SCALING '$(SCALING)')
endif
ifeq ($(LOGGER_ID),)
$(error LOGGER must be off or on)
endif
ifeq ($(HPM_ID),)
$(error HPM must be off or on)
endif
ifneq ($(filter $(HPM_COUNTERS),0 1 2 3 4),$(HPM_COUNTERS))
$(error HPM_COUNTERS must be between 0 and 4)
endif
ifeq ($(HPM),on)
ifeq ($(HPM_COUNTERS),0)
$(error HPM=on requires at least one counter)
endif
endif
ifneq ($(filter $(CPU_COUNT),1 2 4),$(CPU_COUNT))
$(error CPU_COUNT must be 1, 2, or 4)
endif
ifeq ($(CPU_COUNT),1)
ifneq ($(PHASE),single)
$(error CPU_COUNT=1 requires PHASE=single)
endif
else
ifeq ($(PHASE),single)
$(error CPU_COUNT=2/4 requires PHASE=same, phase_shifted, or opposite)
endif
endif
ifneq ($(filter $(SUITE),fault all),)
ifneq ($(LOGGER),on)
$(error fault/all suites require LOGGER=on)
endif
endif

HPM_TAG := $(if $(filter on,$(HPM)),_hpm$(HPM_COUNTERS),)
OBJDIR ?= build/cpu$(CPU_COUNT)_$(SUITE)_$(LOGGER)_$(ORDER)_$(PHASE)_$(SCALING)$(HPM_TAG)
CC := $(RISCV_PATH)/bin/$(RISCV_NAME)-gcc
OBJCOPY := $(RISCV_PATH)/bin/$(RISCV_NAME)-objcopy
OBJDUMP := $(RISCV_PATH)/bin/$(RISCV_NAME)-objdump
CPPFLAGS := -Iinclude -DCPU_COUNT=$(CPU_COUNT) -DPERF_SUITE=$(SUITE_ID) \
  -DPERF_LOGGER=$(LOGGER_ID) -DPERF_ORDER=$(ORDER_ID) \
  -DPERF_PHASE=$(PHASE_ID) -DPERF_SCALING=$(SCALING_ID) \
  -DPERF_HPM_ENABLE=$(HPM_ID) -DPERF_HPM_COUNTERS=$(HPM_COUNTERS) \
  -DPERF_HPM_EVENT0=$(HPM_EVENT0) -DPERF_HPM_EVENT1=$(HPM_EVENT1) \
  -DPERF_HPM_EVENT2=$(HPM_EVENT2) -DPERF_HPM_EVENT3=$(HPM_EVENT3) \
  -DPERF_HPM_EVENT0_VALUE=$(HPM_EVENT0) -DPERF_HPM_EVENT1_VALUE=$(HPM_EVENT1) \
  -DPERF_HPM_EVENT2_VALUE=$(HPM_EVENT2) -DPERF_HPM_EVENT3_VALUE=$(HPM_EVENT3)
COMMON_FLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -mno-relax -Os \
  -ffreestanding -fno-builtin -fno-stack-protector -ffunction-sections -fdata-sections
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -nostdlib -nostartfiles \
  -Wl,-Bstatic,-T,linker.ld,-Map,$(OBJDIR)/$(PROJ_NAME).map,--build-id=none,--gc-sections

C_SOURCES := src/perf.c
ASM_SOURCES := src/startup.S
OBJS := $(patsubst src/%.c,$(OBJDIR)/%.o,$(C_SOURCES)) \
        $(patsubst src/%.S,$(OBJDIR)/%.o,$(ASM_SOURCES))
DEPS := $(OBJS:.o=.d)

.PHONY: all compile clean report test-report matrix-list
all: compile
compile: $(OBJDIR)/$(PROJ_NAME).elf $(OBJDIR)/$(PROJ_NAME).bin $(OBJDIR)/$(PROJ_NAME).asm
$(OBJDIR):
	mkdir -p $@
$(OBJDIR)/%.o: src/%.c
	mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@
$(OBJDIR)/%.o: src/%.S
	mkdir -p $(dir $@)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@
$(OBJDIR)/$(PROJ_NAME).elf: $(OBJS) linker.ld
	$(CC) $(LDFLAGS) -o $@ $(OBJS) -lgcc
$(OBJDIR)/$(PROJ_NAME).bin: $(OBJDIR)/$(PROJ_NAME).elf
	$(OBJCOPY) -O binary $< $@
$(OBJDIR)/$(PROJ_NAME).asm: $(OBJDIR)/$(PROJ_NAME).elf
	$(OBJDUMP) -S -d $< > $@
report:
	@test -n "$(LOG)" || { echo "usage: make report LOG=/path/to/log"; exit 2; }
	python3 tools/perf_report.py "$(LOG)"
test-report:
	python3 -m unittest -v tests/test_perf_report.py
matrix-list:
	bash tools/run_matrix.sh --dry-run
clean:
	rm -rf build
-include $(DEPS)
