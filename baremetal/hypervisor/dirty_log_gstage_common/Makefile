TOOLCHAIN_PREFIX ?= $(if $(RISCV_NAME),$(RISCV_NAME),riscv64-elf)
RISCV_PATH ?= /usr
MARCH ?= rv64gc
MABI ?= lp64d
COMMON_DIR ?= .
PROJ_NAME ?= dirty_log_gstage_common
CASE_FIRST ?= 0
CASE_LIMIT ?= 32
TRACKED_PAGES ?= 128

CC := $(RISCV_PATH)/bin/$(TOOLCHAIN_PREFIX)-gcc
OBJCOPY := $(RISCV_PATH)/bin/$(TOOLCHAIN_PREFIX)-objcopy
OBJDUMP := $(RISCV_PATH)/bin/$(TOOLCHAIN_PREFIX)-objdump

BUILD_DIR ?= $(if $(OBJDIR),$(OBJDIR),build)
ARCH_FLAGS := -march=$(MARCH) -mabi=$(MABI) -mcmodel=medany
CPPFLAGS := -I$(COMMON_DIR)/include -I$(COMMON_DIR)/src \
            -DDIRTYGEN_CASE_FIRST=$(CASE_FIRST) \
            -DDIRTYGEN_CASE_LIMIT=$(CASE_LIMIT) \
            -DDIRTYGEN_TRACKED_PAGES=$(TRACKED_PAGES)
COMMON_FLAGS := $(ARCH_FLAGS) -Os -ffreestanding -fno-builtin \
                -ffunction-sections -fdata-sections
CFLAGS := $(COMMON_FLAGS) -std=c11 -Wall -Wextra -Werror \
          -Wno-missing-field-initializers
ASFLAGS := $(COMMON_FLAGS)
MAP := $(BUILD_DIR)/$(PROJ_NAME).map
LDFLAGS := $(ARCH_FLAGS) -nostdlib -nostartfiles -static \
           -Wl,-T,$(COMMON_DIR)/linker.ld,-Map,$(MAP),--gc-sections

C_SOURCES := dirtygen.c dirty_log_check.c dirty_log_random.c page_table.c
OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(C_SOURCES)) \
           $(BUILD_DIR)/startup.o
DEPS := $(OBJECTS:.o=.d)
ELF := $(BUILD_DIR)/$(PROJ_NAME).elf
BIN := $(BUILD_DIR)/$(PROJ_NAME).bin
ASM := $(BUILD_DIR)/$(PROJ_NAME).asm

.PHONY: all compile clean

all: compile

compile: $(ELF) $(BIN) $(ASM)

$(ELF): $(OBJECTS) $(COMMON_DIR)/linker.ld | $(BUILD_DIR)
	$(CC) $(OBJECTS) $(LDFLAGS) -lgcc -o $@

$(BIN): $(ELF)
	$(OBJCOPY) -O binary $< $@

$(ASM): $(ELF)
	$(OBJDUMP) -S -d $< > $@

$(BUILD_DIR)/dirtygen.o: $(COMMON_DIR)/src/dirtygen.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR)/dirty_log_check.o: $(COMMON_DIR)/src/dirty_log_check.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR)/dirty_log_random.o: $(COMMON_DIR)/src/dirty_log_random.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR)/page_table.o: $(COMMON_DIR)/src/page_table.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR)/startup.o: $(COMMON_DIR)/src/startup.S | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR):
	mkdir -p $@

clean:
	rm -rf $(BUILD_DIR)

-include $(DEPS)
