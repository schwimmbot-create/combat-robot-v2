set(srcs "src/web_config.cpp")

set(requires
        arduino
        ble_gamepad)

idf_component_register(SRCS "${srcs}"
                INCLUDE_DIRS "include"
                REQUIRES ${requires})