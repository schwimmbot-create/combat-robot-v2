set(srcs
        "main.c"
        "sketch.cpp")

set(requires "myrobot" "ble_gamepad" "web_config")

idf_component_register(SRCS "${srcs}"
                    INCLUDE_DIRS "."
                    REQUIRES "${requires}")