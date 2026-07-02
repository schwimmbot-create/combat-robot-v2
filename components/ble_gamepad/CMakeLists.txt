set(srcs "src/ble_gamepad.cpp")

# We do NOT require the 'nimble' component here. NimBLE is BUNDLED with
# the ESP-IDF platform (v5.x) and its headers are on the platform's
# include path (host/ble_hs.h, nimble/nimble_port.h, etc.). Requiring
# 'nimble' as a component causes CMake to look for a managed component
# that doesn't exist in ESP-IDF v5.x.
set(requires
        arduino
        nvs_flash)

idf_component_register(SRCS "${srcs}"
                INCLUDE_DIRS "include"
                REQUIRES ${requires})