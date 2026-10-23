cmake_minimum_required(VERSION 3.22.1)
project(memoryroute)

add_library(memoryroute SHARED
    jni_bridge.cpp
    ../../../../../router/memory_route.cpp)

target_compile_definitions(memoryroute PRIVATE MEMORY_ROUTE_JNI)
target_compile_features(memoryroute PRIVATE cxx_std_17)

find_library(log-lib log)
target_link_libraries(memoryroute ${log-lib})
