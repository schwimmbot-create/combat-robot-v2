set(srcs "src/output_config.c")

# Pure C, depends only on NVS flash for persistence. Web consumers
# read the JSON via web_config which depends on output_config.
set(requires
        nvs_flash)

idf_component_register(SRCS "${srcs}"
                INCLUDE_DIRS "include"
                REQUIRES ${requires})
