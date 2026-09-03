PROJ_NAME := rtl_directed_shdlt
RISCV_PATH ?= /usr
RISCV_NAME ?= riscv64-elf
MARCH ?= rv64gc
MABI ?= lp64d
OBJDIR ?= build/csr

NAX_ROOT := $(abspath $(CURDIR)/../..)
VEXII_ROOT := $(abspath $(NAX_ROOT)/../..)
MANIFEST := $(CURDIR)/binaries.sha256
DIRTYGEN_DIR := $(NAX_ROOT)/benchmarks/dirtygen
SMOKE_DIR := $(NAX_ROOT)/baremetal/multicore_smoke_shdlt
RACE_DIR := $(NAX_ROOT)/baremetal/multicore_race_shdlt
CTC_DIR := $(NAX_ROOT)/benchmarks/cache_tlb_shdlt

SMOKE_CASES := load_only log_off predirty widths nonzero_index freeze reset_resume
RACE_CASES := different_pages buffer_isolation same_pte same_cacheline_ptes
CTC_CASES := pte_cache_hit_miss remote_pte_reread ownership_transfer \
             coherence_pressure cas_retry hfence_before_after hfence_gpa \
             hfence_vmid hfence_global fence_hart_isolation

CC := $(RISCV_PATH)/bin/$(RISCV_NAME)-gcc
OBJCOPY := $(RISCV_PATH)/bin/$(RISCV_NAME)-objcopy
OBJDUMP := $(RISCV_PATH)/bin/$(RISCV_NAME)-objdump
CFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -mno-relax -Os \
          -ffreestanding -fno-builtin -fno-stack-protector -msmall-data-limit=0 \
          -Iinclude
LDFLAGS := -march=$(MARCH)_zicsr -mabi=$(MABI) -mcmodel=medany -nostdlib \
           -nostartfiles -Wl,-Bstatic,-T,linker.ld,-Map,$(OBJDIR)/$(PROJ_NAME).map,--build-id=none

OBJS := $(OBJDIR)/startup.o $(OBJDIR)/runtime.o

.PHONY: all compile matrix-binaries refresh-matrix-manifest \
        verify-matrix-binaries clean test-report
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

matrix-binaries:
	$(MAKE) -C $(DIRTYGEN_DIR) SUITE=dirtygen BUILD_DIR=build all
	@set -e; \
	for cpu in 2 4; do \
	  for test_case in $(SMOKE_CASES); do \
	    if [ "$$cpu" = 2 ]; then \
	      objdir="build/cpu2s_rv64gc_$${test_case}_shdlt"; \
	    else \
	      objdir="build/final4_$${test_case}"; \
	    fi; \
	    $(MAKE) -C $(SMOKE_DIR) CPU_COUNT="$$cpu" CASE="$$test_case" \
	      OBJDIR="$$objdir" compile; \
	  done; \
	done
	@set -e; \
	for cpu in 2 4; do \
	  for test_case in $(RACE_CASES); do \
	    $(MAKE) -C $(RACE_DIR) CPU_COUNT="$$cpu" CASE="$$test_case" \
	      OBJDIR="build/cpu$${cpu}_$${test_case}" compile; \
	  done; \
	done
	@set -e; \
	for cpu in 2 4; do \
	  for test_case in $(CTC_CASES); do \
	    $(MAKE) -C $(CTC_DIR) CPU_COUNT="$$cpu" CASE="$$test_case" \
	      OBJDIR="build/cpu$${cpu}_$${test_case}" compile; \
	  done; \
	done

refresh-matrix-manifest: matrix-binaries
	@manifest_tmp=$$(mktemp "$(MANIFEST).tmp.XXXXXX"); \
	trap 'rm -f "$$manifest_tmp"' EXIT; \
	cd $(VEXII_ROOT); \
	while read -r old_hash binary; do \
	  sha256sum "$$binary" || exit 1; \
	done < $(MANIFEST) > "$$manifest_tmp"; \
	mv "$$manifest_tmp" $(MANIFEST); \
	trap - EXIT

verify-matrix-binaries: matrix-binaries
	cd $(VEXII_ROOT) && sha256sum -c $(MANIFEST)

test-report:
	python3 -m unittest discover -s tests -p 'test_*.py'

clean:
	rm -rf build
