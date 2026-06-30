set(srcs "src/ble_gamepad.cpp")

set(requires
        arduino
        nimble
        nvs_flash)

idf_component_register(SRCS "${srcs}"
                INCLUDE_DIRS "include"
                REQUIRES ${requires})