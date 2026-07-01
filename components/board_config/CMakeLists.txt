set(srcs
        "src/board_detect.cpp")

set(requires
        arduino
        nvs_flash
        driver
        esp_log)

idf_component_register(SRCS "${srcs}"
                INCLUDE_DIRS "include"
                REQUIRES ${requires})