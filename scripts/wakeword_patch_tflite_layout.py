#!/usr/bin/env python3
# ruff: noqa: T201
"""Patch a DNN wake-word TFLite from training layout to pyopen_wakeword layout.

The local trainer exports DNN models with input shape [1, 96, context].
rhasspy/wyoming-openwakeword uses pyopen_wakeword, which feeds custom models as
[1, context, 96]. For a pure flattened DNN, we can preserve behavior by:

1. changing the input tensor metadata to [1, context, 96]
2. permuting columns of the first FullyConnected weight matrix

No TensorFlow converter is needed.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import flatbuffers
import numpy as np
from ai_edge_litert import schema_py_generated as schema_fb


FEATURES = 96


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--features", type=int, default=FEATURES)
    parser.add_argument("--verify", action=argparse.BooleanOptionalAction, default=True)
    return parser


def load_model(path: Path) -> schema_fb.ModelT:
    data = path.read_bytes()
    return schema_fb.ModelT.InitFromObj(schema_fb.Model.GetRootAsModel(data, 0))


def model_input_shape(path: Path) -> list[int]:
    import ai_edge_litert.interpreter as tflite

    interpreter = tflite.Interpreter(model_path=str(path))
    return list(interpreter.get_input_details()[0]["shape"])


def invoke(path: Path, inputs: np.ndarray) -> np.ndarray:
    import ai_edge_litert.interpreter as tflite

    interpreter = tflite.Interpreter(model_path=str(path))
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    interpreter.resize_tensor_input(input_detail["index"], inputs.shape, strict=False)
    interpreter.allocate_tensors()
    interpreter.set_tensor(input_detail["index"], inputs.astype(np.float32))
    interpreter.invoke()
    return interpreter.get_tensor(output_detail["index"])


def patch_layout(model: schema_fb.ModelT, features: int) -> tuple[int, int]:
    subgraph = model.subgraphs[0]
    input_tensor = subgraph.tensors[subgraph.inputs[0]]
    shape = [int(value) for value in input_tensor.shape]
    if len(shape) != 3:
        raise SystemExit(f"Expected rank-3 input tensor, got {shape}")
    if shape[1] != features:
        raise SystemExit(f"Expected training input shape [1,{features},context], got {shape}")

    context = shape[2]
    flattened = features * context

    first_weight_tensor = None
    for tensor in subgraph.tensors:
        tensor_shape = [int(value) for value in tensor.shape]
        if len(tensor_shape) == 2 and tensor_shape[1] == flattened:
            first_weight_tensor = tensor
            break

    if first_weight_tensor is None:
        raise SystemExit(f"Could not find first dense weight tensor with input size {flattened}")

    hidden = int(first_weight_tensor.shape[0])
    buffer = model.buffers[first_weight_tensor.buffer]
    weights = np.frombuffer(bytes(buffer.data), dtype="<f4").copy()
    expected = hidden * flattened
    if weights.size != expected:
        raise SystemExit(f"Unexpected first dense weight size: {weights.size}, expected {expected}")

    weights = weights.reshape(hidden, features, context).transpose(0, 2, 1).reshape(hidden, flattened)
    buffer.data = np.frombuffer(weights.astype("<f4", copy=False).tobytes(), dtype=np.uint8)

    input_tensor.shape = np.asarray([1, context, features], dtype=np.int32)
    input_tensor.shapeSignature = np.asarray([-1, context, features], dtype=np.int32)
    return context, hidden


def write_model(model: schema_fb.ModelT, path: Path) -> None:
    builder = flatbuffers.Builder(0)
    model_offset = model.Pack(builder)
    builder.Finish(model_offset, file_identifier=b"TFL3")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(builder.Output()))


def verify_equivalence(old_path: Path, new_path: Path, context: int, features: int) -> float:
    rng = np.random.default_rng(20260612)
    old_inputs = rng.normal(0, 1, size=(4, features, context)).astype(np.float32)
    new_inputs = np.transpose(old_inputs, (0, 2, 1))
    old_outputs = invoke(old_path, old_inputs)
    new_outputs = invoke(new_path, new_inputs)
    return float(np.max(np.abs(old_outputs - new_outputs)))


def main() -> None:
    args = build_parser().parse_args()
    model = load_model(args.input)
    context, hidden = patch_layout(model, args.features)
    write_model(model, args.output)

    output_shape = model_input_shape(args.output)
    print(f"Wrote {args.output}")
    print(f"Patched input shape: {output_shape}, context={context}, hidden={hidden}")

    if args.verify:
        max_abs_diff = verify_equivalence(args.input, args.output, context, args.features)
        print(f"Old/new transpose equivalence max_abs_diff={max_abs_diff:.8g}")
        if max_abs_diff > 1e-5:
            raise SystemExit("Patched model is not equivalent to original layout")


if __name__ == "__main__":
    main()
