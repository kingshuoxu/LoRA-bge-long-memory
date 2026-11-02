CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra

.PHONY: all clean aarch64

all: memory-route

memory-route: memory_route.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

# Linux arm64 静态二进制,给 qemu-user 做冒烟。安卓真机用 Termux 的 g++ 编同一份源码。
aarch64: memory_route.cpp
	aarch64-linux-gnu-g++ $(CXXFLAGS) -static -o memory-route-aarch64 $<

clean:
	rm -f memory-route memory-route-aarch64
