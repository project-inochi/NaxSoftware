ifeq ($(BR2_TARGET_OPENSBI),y)
ifeq ($(BR2_riscv),y)

OPENSBI_USER_VARS := $(call qstrip,$(BR2_TARGET_OPENSBI_ADDITIONAL_VARIABLES))

# Preserve explicit user override from OpenSBI "Additional build variables".
ifeq ($(filter PLATFORM_RISCV_ISA=%,$(OPENSBI_USER_VARS)),)
OPENSBI_MAKE_ENV += PLATFORM_RISCV_ISA=$(GCC_TARGET_ARCH)
endif

ifeq ($(filter PLATFORM_RISCV_ABI=%,$(OPENSBI_USER_VARS)),)
OPENSBI_MAKE_ENV += PLATFORM_RISCV_ABI=$(BR2_GCC_TARGET_ABI)
endif

endif
endif
