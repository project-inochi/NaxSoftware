CPU_COUNT ?= 2
ifneq ($(filter $(CPU_COUNT),1 2 4),$(CPU_COUNT))
$(error CPU_COUNT must be 1, 2 or 4)
endif

PROJ_NAME=multicore_smoke
OBJDIR?=build/cpu$(CPU_COUNT)
CFLAGS_ARGS += -DCPU_COUNT=$(CPU_COUNT)
ifeq ($(SUPERVISOR),yes)
CFLAGS_ARGS += -DTEST_SUPERVISOR
endif
LDFLAGS += -Wl,--build-id=none

include ../common/asm.mk
