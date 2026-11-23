/// @file
/// Filling and summing a Buffer<double> of a million elements: the cost of
/// the raw layer's view against the memory it walks.
#define ANKERL_NANOBENCH_IMPLEMENT
#include <nanobench.h>

#include "raw/buffer.hpp"

#include <cstddef>

namespace {

/// The elements each run fills and sums.
constexpr std::size_t elements = 1'000'000;

} // namespace

/// Run the benchmarks and print nanobench's table.
/// @return 0.
int main() {
    sq::raw::Buffer<double> buffer(elements);
    ankerl::nanobench::Bench bench;
    bench.title("raw::Buffer<double> of 1e6").unit("element").batch(elements).minEpochIterations(100);

    bench.run("fill", [&] {
        std::size_t i = 0;
        for (auto &element : buffer.span()) {
            element = static_cast<double>(i++);
        }
        ankerl::nanobench::doNotOptimizeAway(buffer.span().data());
    });

    bench.run("sum", [&] {
        double sum = 0.0;
        for (const auto element : buffer.span()) {
            sum += element;
        }
        ankerl::nanobench::doNotOptimizeAway(sum);
    });
    return 0;
}
