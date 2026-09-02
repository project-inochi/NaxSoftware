PROJ_NAME := multicore_smoke_shdlt
CPU_COUNT ?= 2
CASE ?= legacy
RISCV_PATH ?= /usr
RISCV_NAME ?= riscv64-elf
MARCH ?= rv64gc
MABI ?= lp64d
SUPERVISOR ?= yes
ifeq ($(CASE),legacy)
OBJDIR ?= build/cpu$(CPU_COUNT)s_$(MARCH)_shdlt
else
OBJDIR ?= build/cpu$(CPU_COUNT)s_$(MARCH)_$(CASE)_shdlt
endif

CASE_ID_legacy := 0
CASE_ID_load_only := 1
CASE_ID_log_off := 2
CASE_ID_predirty := 3
CASE_ID_widths := 4
CASE_ID_nonzero_index := 5
CASE_ID_freeze := 6
CASE_ID_reset_resume := 7
CASE_ID := $(CASE_ID_$(CASE))
ifeq ($(CASE_ID),)
$(error CASE must be one of legacy load_only log_off predirty widths nonzero_index freeze reset_resume)
endif

ifneq ($(filter $(CPU_COUNT),2 4),$(CPU_COUNT))
$(error CPU_COUNT must be 2 or 4)
endif
ifeq ($(SUPERVISOR),yes)
CFLAGS_SUPERVISOR := -DSUPERVISOR
endif

CC := $(RISCV_PATH)/bin/$(RISCV_NAME)-gcc
OBJCOPY := $(RISCV_PATH)/bin/$(RISCV_NAME)-objcopy
OBJDUMP := $(RISCV_PATH)/bin/$(RISCV_NAME)-objdump
CFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -mno-relax -Os \
          -ffreestanding -fno-builtin -fno-stack-protector \
          -Iinclude -DCPU_COUNT=$(CPU_COUNT) -DSHDLT_CASE=$(CASE_ID) $(CFLAGS_SUPERVISOR)
LDFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -nostdlib \
           -nostartfiles -Wl,-Bstatic,-T,linker.ld,-Map,$(OBJDIR)/$(PROJ_NAME).map,--build-id=none

OBJS := $(OBJDIR)/startup.o $(OBJDIR)/page_table.o $(OBJDIR)/dirty_log.o $(OBJDIR)/multicore_shdlt.o

.PHONY: all compile clean
all: compile

compile: $(OBJDIR)/$(PROJ_NAME).elf $(OBJDIR)/$(PROJ_NAME).bin $(OBJDIR)/$(PROJ_NAME).asm

$(OBJDIR):
	@mkdir -p $@

$(OBJDIR)/%.o: src/%.S | $(OBJDIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(OBJDIR)/%.o: src/%.c | $(OBJDIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(OBJDIR)/$(PROJ_NAME).elf: $(OBJS) linker.ld | $(OBJDIR)
	$(CC) $(LDFLAGS) -o $@ $(OBJS) -lgcc

$(OBJDIR)/$(PROJ_NAME).bin: $(OBJDIR)/$(PROJ_NAME).elf
	$(OBJCOPY) -O binary $< $@

$(OBJDIR)/$(PROJ_NAME).asm: $(OBJDIR)/$(PROJ_NAME).elf
	$(OBJDUMP) -S -d $< > $@

clean:
	rm -rf build
