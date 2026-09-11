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
else ifeq ($(SUITE),perf-mc)
BUILD_DIR ?= build/perf-mc-v2-h1-private-strong-b0
IMAGE_NAME := dirtygen_perf_mc
ARCH_FLAGS := -march=rv64ia_zicsr -mabi=lp64 -mcmodel=medany
SUITE_COMMON_FLAGS := -mno-relax -fno-stack-protector
SUITE_LDFLAGS := -Wl,--build-id=none
LINKER_SCRIPT := linker_perf_mc.ld
C_SOURCES := \
  src/dirtygen_perf_mc.c \
  src/dirtygen_perf_mc_page_table.c \
  src/dirtygen_perf_mc_selection.c
ASM_SOURCES := \
  src/dirtygen_perf_mc_startup.S \
  src/dirtygen_perf_mc_guest.S
else ifeq ($(SUITE),perf-mc-prefilled)
BUILD_DIR ?= build/perf-mc-v2-prefilled-h2-b2
IMAGE_NAME := dirtygen_perf_mc_prefilled
ARCH_FLAGS := -march=rv64ia_zicsr -mabi=lp64 -mcmodel=medany
SUITE_COMMON_FLAGS := -mno-relax -fno-stack-protector
SUITE_LDFLAGS := -Wl,--build-id=none
SUITE_CPPFLAGS := -DDIRTYGEN_PERF_MC_PREFILLED
LINKER_SCRIPT := linker_perf_mc.ld
C_SOURCES := \
  src/dirtygen_perf_mc.c \
  src/dirtygen_perf_mc_page_table.c \
  src/dirtygen_perf_mc_prefilled_selection.c
ASM_SOURCES := \
  src/dirtygen_perf_mc_startup.S \
  src/dirtygen_perf_mc_prefilled_guest.S
else ifeq ($(SUITE),buffer-mc)
BUILD_DIR ?= build/buffer-mc-v1-h2-stale-d-full
IMAGE_NAME := dirtygen_buffer_mc
ARCH_FLAGS := -march=rv64ia_zicsr -mabi=lp64 -mcmodel=medany
SUITE_COMMON_FLAGS := -mno-relax -fno-stack-protector
SUITE_LDFLAGS := -Wl,--build-id=none
SUITE_CPPFLAGS := -DDIRTYGEN_BUFFER_MC_HARTS=$(BUFFER_MC_HARTS)
LINKER_SCRIPT := linker_buffer_mc.ld
C_SOURCES := \
  src/dirtygen_buffer_mc.c \
  src/dirtygen_buffer_mc_page_table.c
ASM_SOURCES := \
  src/dirtygen_buffer_mc_startup.S \
  src/dirtygen_buffer_mc_guest.S
else ifeq ($(SUITE),buffer-boundary)
BUILD_DIR ?= build/buffer-boundary-v1-h1
IMAGE_NAME := dirtygen_buffer_boundary_mc
ARCH_FLAGS := -march=rv64ia_zicsr -mabi=lp64 -mcmodel=medany
SUITE_COMMON_FLAGS := -mno-relax -fno-stack-protector
SUITE_LDFLAGS := -Wl,--build-id=none
SUITE_CPPFLAGS := -DBOUNDARY_MC_HARTS=$(BOUNDARY_MC_HARTS) \
                  -DBOUNDARY_MC_PROFILE=$(BOUNDARY_MC_PROFILE)
LINKER_SCRIPT := linker_buffer_boundary_mc.ld
C_SOURCES := \
  src/dirtygen_buffer_boundary_mc.c \
  src/dirtygen_buffer_boundary_mc_page_table.c
ASM_SOURCES := \
  src/dirtygen_buffer_boundary_mc_startup.S \
  src/dirtygen_buffer_boundary_mc_guest.S
else ifeq ($(SUITE),dirtygen)
BUILD_DIR ?= build
IMAGE_NAME := dirtygen
C_SOURCES := \
  src/dirtygen.c \
  src/dirty_log_check.c \
  src/dirty_log_random.c \
  src/page_table.c
else
$(error SUITE must be dirtygen, phase1, phase6, perf, perf-mc, perf-mc-prefilled, buffer-mc, or buffer-boundary)
endif

CASE_FIRST ?= 0
CASE_LIMIT ?= 32

ARCH_FLAGS ?= -march=rv64i_zicsr -mabi=lp64 -mcmodel=medany
CPPFLAGS := -Iinclude -Isrc \
            -DDIRTYGEN_CASE_FIRST=$(CASE_FIRST) \
            -DDIRTYGEN_CASE_LIMIT=$(CASE_LIMIT) \
            $(SUITE_CPPFLAGS)
COMMON_FLAGS := $(ARCH_FLAGS) -Os -ffreestanding -fno-builtin \
                -ffunction-sections -fdata-sections $(SUITE_COMMON_FLAGS)
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror \
          -Wno-missing-field-initializers
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := $(ARCH_FLAGS) -nostdlib -nostartfiles -static \
           -Wl,-T,$(or $(LINKER_SCRIPT),linker.ld),-Map,$(BUILD_DIR)/dirtygen.map,--gc-sections \
           $(SUITE_LDFLAGS)

ASM_SOURCES ?= src/startup.S
OBJECTS := $(patsubst src/%.c,$(BUILD_DIR)/%.o,$(C_SOURCES)) \
           $(patsubst src/%.S,$(BUILD_DIR)/%.o,$(ASM_SOURCES))
DEPS := $(OBJECTS:.o=.d)

.PHONY: all phase1 phase6 perf perf-rvls-smoke perf-isolated perf-mc perf-mc-prefilled buffer-mc \
        buffer-boundary-h1 buffer-boundary-mc buffer-boundary-stress clean report \
        perf-report perf-mc-report \
        test-report test-phase1-report test-phase6-report \
        test-perf-report test-perf-campaign test-perf-compare \
        test-perf-mc-report test-perf-mc-campaign test-perf-mc-compare \
        test-buffer-mc-report test-buffer-boundary-report test-perf

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

PERF_MC_HARTS ?= 1
PERF_MC_WORKLOAD ?= private-strong
PERF_MC_BASELINE ?= 0
PERF_MC_WORKLOAD_ID_private-strong := 0
PERF_MC_WORKLOAD_ID_private-weak := 1
PERF_MC_WORKLOAD_ID_same-pte := 2
PERF_MC_WORKLOAD_ID := $(PERF_MC_WORKLOAD_ID_$(PERF_MC_WORKLOAD))

perf-mc:
	@case "$(PERF_MC_HARTS)" in 1|2|4) ;; *) \
		echo "PERF_MC_HARTS must be 1, 2, or 4"; exit 2;; esac
	@test -n "$(PERF_MC_WORKLOAD_ID)" || { \
		echo "PERF_MC_WORKLOAD must be private-strong, private-weak, or same-pte"; exit 2; }
	@case "$(PERF_MC_BASELINE)" in 0|1|2|3) ;; *) \
		echo "PERF_MC_BASELINE must be 0, 1, 2, or 3"; exit 2;; esac
	$(MAKE) SUITE=perf-mc \
		BUILD_DIR=build/perf-mc-v2-h$(PERF_MC_HARTS)-$(PERF_MC_WORKLOAD)-b$(PERF_MC_BASELINE) \
		PERF_MC_HARTS=$(PERF_MC_HARTS) \
		PERF_MC_WORKLOAD_ID=$(PERF_MC_WORKLOAD_ID) \
		PERF_MC_BASELINE=$(PERF_MC_BASELINE) all

perf-mc-prefilled:
	@case "$(PERF_MC_HARTS)" in 2|4) ;; *) \
		echo "PERF_MC_HARTS must be 2 or 4 for prefilled SAME_PTE"; exit 2;; esac
	@case "$(PERF_MC_BASELINE)" in 2|3) ;; *) \
		echo "PERF_MC_BASELINE must be 2 or 3 for prefilled SAME_PTE"; exit 2;; esac
	$(MAKE) SUITE=perf-mc-prefilled \
		BUILD_DIR=build/perf-mc-v2-prefilled-h$(PERF_MC_HARTS)-b$(PERF_MC_BASELINE) \
		PERF_MC_HARTS=$(PERF_MC_HARTS) \
		PERF_MC_BASELINE=$(PERF_MC_BASELINE) all

BUFFER_MC_HARTS ?= 2

buffer-mc:
	@case "$(BUFFER_MC_HARTS)" in 2|4) ;; *) \
		echo "the Phase-4 minimal gate requires BUFFER_MC_HARTS=2 or 4"; exit 2;; esac
	$(MAKE) SUITE=buffer-mc \
		BUILD_DIR=build/buffer-mc-v1-h$(BUFFER_MC_HARTS)-stale-d-full \
		BUFFER_MC_HARTS=$(BUFFER_MC_HARTS) all

buffer-boundary-h1:
	$(MAKE) SUITE=buffer-boundary \
		BUILD_DIR=build/buffer-boundary-v1-h1 \
		BOUNDARY_MC_HARTS=1 BOUNDARY_MC_PROFILE=1 all

BOUNDARY_MC_HARTS ?= 2

buffer-boundary-mc:
	@case "$(BOUNDARY_MC_HARTS)" in 2|4) ;; *) \
		echo "BOUNDARY_MC_HARTS must be 2 or 4"; exit 2;; esac
	$(MAKE) SUITE=buffer-boundary \
		BUILD_DIR=build/buffer-boundary-v1-h$(BOUNDARY_MC_HARTS) \
		BOUNDARY_MC_HARTS=$(BOUNDARY_MC_HARTS) BOUNDARY_MC_PROFILE=2 all

buffer-boundary-stress:
	@case "$(BOUNDARY_MC_HARTS)" in 1|2|4) ;; *) \
		echo "BOUNDARY_MC_HARTS must be 1, 2, or 4"; exit 2;; esac
	$(MAKE) SUITE=buffer-boundary \
		BUILD_DIR=build/buffer-boundary-stress-v2-h$(BOUNDARY_MC_HARTS) \
		BOUNDARY_MC_HARTS=$(BOUNDARY_MC_HARTS) BOUNDARY_MC_PROFILE=3 all

test-buffer-mc-report:
	python3 -m unittest -v tests.test_dirtygen_buffer_mc_report

test-buffer-boundary-report:
	python3 -m unittest -v tests.test_dirtygen_buffer_boundary_report \
		tests.test_dirtygen_buffer_stress_phase4

$(BUILD_DIR)/$(IMAGE_NAME).elf: $(OBJECTS) $(or $(LINKER_SCRIPT),linker.ld) | $(BUILD_DIR)
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

ifeq ($(SUITE),perf-mc)
$(BUILD_DIR)/dirtygen_perf_mc_selection.o: src/dirtygen_perf_mc_selection.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) \
		-DDIRTYGEN_PERF_MC_HARTS=$(PERF_MC_HARTS) \
		-DDIRTYGEN_PERF_MC_WORKLOAD=$(PERF_MC_WORKLOAD_ID) \
		-DDIRTYGEN_PERF_MC_BASELINE=$(PERF_MC_BASELINE) \
		-MMD -MP -c $< -o $@
endif

ifeq ($(SUITE),perf-mc-prefilled)
$(BUILD_DIR)/dirtygen_perf_mc_prefilled_selection.o: src/dirtygen_perf_mc_prefilled_selection.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) \
		-DDIRTYGEN_PERF_MC_HARTS=$(PERF_MC_HARTS) \
		-DDIRTYGEN_PERF_MC_BASELINE=$(PERF_MC_BASELINE) \
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

perf-mc-report:
	@test -n "$(LOG)" || { echo "usage: make perf-mc-report LOG=/path/to/console TRACE=/path/to/tracer ELF=/path/to/elf PERF_MC_HARTS=1|2|4 PERF_MC_WORKLOAD=private-strong|private-weak|same-pte|prefilled-same-pte PERF_MC_BASELINE=B0|B1|B2|B3"; exit 2; }
	@test -n "$(TRACE)" || { echo "TRACE is required"; exit 2; }
	@test -n "$(ELF)" || { echo "ELF is required"; exit 2; }
	python3 tools/dirtygen_perf_mc_report.py "$(LOG)" \
		--hart-count "$(PERF_MC_HARTS)" --workload "$(PERF_MC_WORKLOAD)" \
		--baseline "$(PERF_MC_BASELINE)" --tracer "$(TRACE)" --elf "$(ELF)"

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

test-perf-mc-report:
	python3 -m unittest -v tests/test_dirtygen_perf_mc_report.py

test-perf-mc-campaign:
	python3 -m unittest -v tests/test_dirtygen_perf_mc_campaign.py

test-perf-mc-compare:
	python3 -m unittest -v tests/test_dirtygen_perf_mc_compare.py

.PHONY: test-isa-consistency
test-isa-consistency:
	python3 -m unittest discover -s tests -p 'test_shdlt_isa.py'
	python3 -m unittest discover -s tests -p 'test_dirtygen_perf_mc*.py'

test-perf: test-perf-report test-perf-campaign test-perf-compare \
	           test-perf-mc-report test-perf-mc-campaign test-perf-mc-compare

clean:
	rm -rf $(BUILD_DIR)

-include $(DEPS)
