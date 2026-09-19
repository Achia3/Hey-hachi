"""Assistant-only labels using the actual Qwen template; no silent truncation."""


def verify_gguf_vocabulary(source, tokenizer):
    """Check active token IDs against the actual source; allow only trailing padding."""
    from gguf import GGUFReader
    reader = GGUFReader(str(source))
    tokens = reader.fields["tokenizer.ggml.tokens"]
    if len(tokens.data) < len(tokenizer):
        raise ValueError("Source vocabulary is smaller than the tokenizer")
    for index, part in enumerate(tokens.data):
        actual = tokens.parts[part].tobytes().decode("utf-8")
        expected = tokenizer.convert_ids_to_tokens(index) if index < len(tokenizer) else f"[PAD{index}]"
        if actual != expected:
            raise ValueError(f"Tokenizer/source vocabulary mismatch at token {index}")
    return len(tokens.data)


def training_examples(record, tokenizer, max_length):
    # One example per assistant turn preserves previous turns as context. Rendering
    # only the current prefix avoids Qwen's last-query-dependent formatting changes.
    examples = []
    messages = record["messages"]
    for i, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        options = {"tokenize": False, "enable_thinking": False}
        if record.get("tools"):
            options["tools"] = record["tools"]
        prompt = tokenizer.apply_chat_template(messages[:i], add_generation_prompt=True, **options)
        full = tokenizer.apply_chat_template(messages[:i + 1], add_generation_prompt=False, **options)
        if not full.startswith(prompt):
            raise ValueError(f"Template prefix mismatch in {record['id']}; do not train with misaligned labels")
        encoded = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
        ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
        # All prompt tokens, including a token straddling the boundary, are masked.
        labels = [token if start >= len(prompt) and end > start else -100
                  for token, (start, end) in zip(ids, offsets)]
        if len(ids) > max_length:
            raise ValueError(f"{record['id']} has {len(ids)} tokens, exceeding {max_length}; no truncation allowed")
        if not any(label != -100 for label in labels):
            raise ValueError("No assistant target tokens: " + record["id"])
        examples.append({"input_ids": ids, "attention_mask": [1] * len(ids), "labels": labels})
    return examples
