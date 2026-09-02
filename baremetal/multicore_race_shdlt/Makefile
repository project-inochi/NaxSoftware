PROJ_NAME := multicore_race_shdlt
CPU_COUNT ?= 2
CASE ?= different_pages
RISCV_PATH ?= /usr
RISCV_NAME ?= riscv64-elf
MARCH ?= rv64gc
MABI ?= lp64d
OBJDIR ?= build/cpu$(CPU_COUNT)_$(CASE)

CASE_ID_different_pages := 0
CASE_ID_order_permute := 1
CASE_ID_skewed_completion := 2
CASE_ID_result_isolation := 3
CASE_ID_buffer_isolation := 4
CASE_ID_same_page := 5
CASE_ID_same_pte := 6
CASE_ID_same_cacheline_ptes := 7
CASE_ID := $(CASE_ID_$(CASE))

ifeq ($(CASE_ID),)
$(error CASE must be one of different_pages order_permute skewed_completion result_isolation buffer_isolation same_page same_pte same_cacheline_ptes)
endif
ifneq ($(filter $(CPU_COUNT),2 4),$(CPU_COUNT))
$(error CPU_COUNT must be 2 or 4)
endif

CC := $(RISCV_PATH)/bin/$(RISCV_NAME)-gcc
OBJCOPY := $(RISCV_PATH)/bin/$(RISCV_NAME)-objcopy
OBJDUMP := $(RISCV_PATH)/bin/$(RISCV_NAME)-objdump
CPPFLAGS := -Iinclude -DCPU_COUNT=$(CPU_COUNT) -DSHDLT_RACE_CASE=$(CASE_ID)
COMMON_FLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -mno-relax -Os \
                -ffreestanding -fno-builtin -fno-stack-protector -ffunction-sections -fdata-sections
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -nostdlib -nostartfiles \
           -Wl,-Bstatic,-T,linker.ld,-Map,$(OBJDIR)/$(PROJ_NAME).map,--build-id=none,--gc-sections

C_SOURCES := src/runtime.c src/page_table.c
ASM_SOURCES := src/startup.S
OBJS := $(patsubst src/%.c,$(OBJDIR)/%.o,$(C_SOURCES)) $(patsubst src/%.S,$(OBJDIR)/%.o,$(ASM_SOURCES))
DEPS := $(OBJS:.o=.d)

.PHONY: all compile clean report test-report
all: compile
compile: $(OBJDIR)/$(PROJ_NAME).elf $(OBJDIR)/$(PROJ_NAME).bin $(OBJDIR)/$(PROJ_NAME).asm

$(OBJDIR):
	mkdir -p $@
$(OBJDIR)/%.o: src/%.c | $(OBJDIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@
$(OBJDIR)/%.o: src/%.S | $(OBJDIR)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@
$(OBJDIR)/$(PROJ_NAME).elf: $(OBJS) linker.ld | $(OBJDIR)
	$(CC) $(LDFLAGS) -o $@ $(OBJS) -lgcc
$(OBJDIR)/$(PROJ_NAME).bin: $(OBJDIR)/$(PROJ_NAME).elf
	$(OBJCOPY) -O binary $< $@
$(OBJDIR)/$(PROJ_NAME).asm: $(OBJDIR)/$(PROJ_NAME).elf
	$(OBJDUMP) -S -d $< > $@

report:
	@test -n "$(LOG)" || { echo "usage: make report LOG=/path/to/log"; exit 2; }
	python3 tools/race_report.py "$(LOG)"
test-report:
	python3 -m unittest -v tests/test_race_report.py
clean:
	rm -rf build
-include $(DEPS)
