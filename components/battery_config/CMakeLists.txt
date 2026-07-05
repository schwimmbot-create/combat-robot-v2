set(srcs "src/battery_config.c")

set(requires
        nvs_flash)

idf_component_register(SRCS "${srcs}"
                INCLUDE_DIRS "include"
                REQUIRES ${requires})
