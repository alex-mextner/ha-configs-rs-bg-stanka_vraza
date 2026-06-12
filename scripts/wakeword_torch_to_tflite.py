#!/usr/bin/env python3
# ruff: noqa: D103, D213, E501, EM101, EM102, EXE001, PLC0415, T201, TRY003
"""Convert a DNN checkpoint from wakeword_iterate.py to a TFLite model.

This script expects TensorFlow to be installed in the active Python
environment. It maps the PyTorch DNN weights directly into an equivalent Keras
model, avoiding ONNX->TensorFlow conversion dependencies.

Default output layout is pyopen_wakeword compatible: [batch, context, 96].
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layout", choices=("pyopen", "training"), default="pyopen")
    parser.add_argument("--float16", action="store_true")
    return parser


def main() -> None:
    try:
        import tensorflow as tf
    except ModuleNotFoundError as err:
        raise SystemExit("TensorFlow is required: pip install tensorflow-cpu") from err

    args = build_parser().parse_args()
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    if checkpoint.get("architecture") != "dnn":
        raise SystemExit(f"Only dnn checkpoints are supported, got {checkpoint.get('architecture')!r}")

    state = checkpoint["state_dict"]
    context_frames = int(checkpoint["context_frames"])
    hidden = int(checkpoint["hidden"])

    if args.layout == "pyopen":
        inputs = tf.keras.Input(shape=(context_frames, 96), batch_size=None, name="input")
        x = tf.keras.layers.Permute((2, 1), name="to_training_layout")(inputs)
    else:
        inputs = tf.keras.Input(shape=(96, context_frames), batch_size=None, name="input")
        x = inputs

    x = tf.keras.layers.Flatten(name="flatten")(x)
    x = tf.keras.layers.Dense(hidden, name="dense1")(x)
    x = tf.keras.layers.LayerNormalization(axis=-1, epsilon=1e-5, name="ln1")(x)
    x = tf.keras.layers.ReLU(name="relu1")(x)
    x = tf.keras.layers.Dense(hidden, name="dense2")(x)
    x = tf.keras.layers.LayerNormalization(axis=-1, epsilon=1e-5, name="ln2")(x)
    x = tf.keras.layers.ReLU(name="relu2")(x)
    outputs = tf.keras.layers.Dense(1, activation="sigmoid", name="output")(x)
    model = tf.keras.Model(inputs=inputs, outputs=outputs)

    model.get_layer("dense1").set_weights(
        [state["1.weight"].numpy().T.astype(np.float32), state["1.bias"].numpy().astype(np.float32)]
    )
    model.get_layer("ln1").set_weights(
        [state["2.weight"].numpy().astype(np.float32), state["2.bias"].numpy().astype(np.float32)]
    )
    model.get_layer("dense2").set_weights(
        [state["5.weight"].numpy().T.astype(np.float32), state["5.bias"].numpy().astype(np.float32)]
    )
    model.get_layer("ln2").set_weights(
        [state["6.weight"].numpy().astype(np.float32), state["6.bias"].numpy().astype(np.float32)]
    )
    model.get_layer("output").set_weights(
        [state["9.weight"].numpy().T.astype(np.float32), state["9.bias"].numpy().astype(np.float32)]
    )

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    if args.float16:
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.target_spec.supported_types = [tf.float16]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(converter.convert())
    print(f"Wrote {args.output}")
    print(f"Input layout: {args.layout}")
    print(f"Recommended threshold: {checkpoint.get('threshold')}")


if __name__ == "__main__":
    main()
