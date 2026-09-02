PROJ_NAME ?= slat_VS_39_dirty_log_boundary_recovery
COMMON_DIR ?= ../dirty_log_gstage_common
# Keep the historical default image focused on the recovery case.  The
# boundary matrix overrides these on the command line and uses a distinct
# OBJDIR for every range.
CASE_FIRST ?= 14
CASE_LIMIT ?= 15
TRACKED_PAGES ?= 128
include $(COMMON_DIR)/Makefile
