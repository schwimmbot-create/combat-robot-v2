set(srcs "src/web_config.cpp")

set(requires
        arduino
        ble_gamepad
        board_config
        board_detect
        battery_config
        output_config)

idf_component_register(SRCS "${srcs}"
                INCLUDE_DIRS "include"
                REQUIRES ${requires})