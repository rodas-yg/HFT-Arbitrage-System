with open('retrainer.py', 'r') as f:
    content = f.read()

target = """        if not os.path.exists(model_path) and not args.binary:
            log.error(f"Model file '{MODEL_PATH}' not found. Aborting.")
            sys.exit(1)

        model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
        log.info(f"  Loaded existing weights from '{model_path}'")"""

replacement = """        if os.path.exists(model_path):
            model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
            log.info(f"  Loaded existing weights from '{model_path}'")
        else:
            if not args.binary:
                log.error(f"Model file '{MODEL_PATH}' not found. Aborting.")
                sys.exit(1)
            else:
                log.info(f"  '{model_path}' not found. Starting with random weights for binary model.")"""

content = content.replace(target, replacement)

with open('retrainer.py', 'w') as f:
    f.write(content)

