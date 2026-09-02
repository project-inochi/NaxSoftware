PROJ_NAME := cache_tlb_shdlt
CPU_COUNT ?= 2
CASE ?= pte_cache_hit_miss
RISCV_PATH ?= /usr
RISCV_NAME ?= riscv64-elf
MARCH ?= rv64gc
MABI ?= lp64d
OBJDIR ?= build/cpu$(CPU_COUNT)_$(CASE)

CASE_ID_pte_cache_hit_miss := 0
CASE_ID_remote_pte_reread := 1
CASE_ID_ownership_transfer := 2
CASE_ID_coherence_pressure := 3
CASE_ID_cas_retry := 4
CASE_ID_hfence_before_after := 5
CASE_ID_hfence_gpa := 6
CASE_ID_hfence_vmid := 7
CASE_ID_hfence_global := 8
CASE_ID_fence_hart_isolation := 9
CASE_ID := $(CASE_ID_$(CASE))

ifeq ($(CASE_ID),)
$(error unknown CASE '$(CASE)')
endif
ifneq ($(filter $(CPU_COUNT),2 4),$(CPU_COUNT))
$(error CPU_COUNT must be 2 or 4)
endif

CC := $(RISCV_PATH)/bin/$(RISCV_NAME)-gcc
OBJCOPY := $(RISCV_PATH)/bin/$(RISCV_NAME)-objcopy
OBJDUMP := $(RISCV_PATH)/bin/$(RISCV_NAME)-objdump
CPPFLAGS := -Iinclude -DCPU_COUNT=$(CPU_COUNT) -DCTC_CASE=$(CASE_ID)
COMMON_FLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -mno-relax -Os \
                -ffreestanding -fno-builtin -fno-stack-protector -ffunction-sections -fdata-sections
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -nostdlib -nostartfiles \
           -Wl,-Bstatic,-T,linker.ld,-Map,$(OBJDIR)/$(PROJ_NAME).map,--build-id=none,--gc-sections

C_SOURCES := src/core/descriptor.c src/core/validator.c src/platform_baremetal.c src/page_table.c src/runtime.c
ASM_SOURCES := src/startup.S
OBJS := $(patsubst src/%.c,$(OBJDIR)/%.o,$(C_SOURCES)) $(patsubst src/%.S,$(OBJDIR)/%.o,$(ASM_SOURCES))
DEPS := $(OBJS:.o=.d)

.PHONY: all compile clean report test-report
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
	python3 tools/ctc_report.py "$(LOG)"
test-report:
	python3 -m unittest -v tests/test_ctc_report.py
clean:
	rm -rf build
-include $(DEPS)
