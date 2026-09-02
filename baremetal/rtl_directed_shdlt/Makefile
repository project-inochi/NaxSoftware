PROJ_NAME := rtl_directed_shdlt
RISCV_PATH ?= /usr
RISCV_NAME ?= riscv64-elf
MARCH ?= rv64gc
MABI ?= lp64d
OBJDIR ?= build/csr

CC := $(RISCV_PATH)/bin/$(RISCV_NAME)-gcc
OBJCOPY := $(RISCV_PATH)/bin/$(RISCV_NAME)-objcopy
OBJDUMP := $(RISCV_PATH)/bin/$(RISCV_NAME)-objdump
CFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -mno-relax -Os \
          -ffreestanding -fno-builtin -fno-stack-protector -msmall-data-limit=0 \
          -Iinclude
LDFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -nostdlib \
           -nostartfiles -Wl,-Bstatic,-T,linker.ld,-Map,$(OBJDIR)/$(PROJ_NAME).map,--build-id=none

OBJS := $(OBJDIR)/startup.o $(OBJDIR)/runtime.o

.PHONY: all compile clean test-report
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

test-report:
	python3 -m unittest discover -s tests -p 'test_*.py'

clean:
	rm -rf build
