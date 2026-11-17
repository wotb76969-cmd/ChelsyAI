# Адаптация LLM (LoRA/QLoRA) — статус 0.9.4

ТЗ MIND-03 требует контролируемую адаптацию языковой модели с реальным адаптером.

## Что есть

- Конвейер `training/finetune.py` и реестр моделей из 0.9.3 сохранены.
- Обученный **Task Router** с весами: `training/datasets/router_weights_v1.json` (метрики в `router_train_report.json`).
- Датасеты router разделены train/val/test, без персональных переписок.

## Что не выполнено в этой среде сборки

Полный LoRA на 7B требует GPU/VRAM и длительного прогона. В текущей CI/агентской VM гарантированной GPU нет — **адаптер LLM не выдаётся как обученный**.

Владельцу: запустить на машине обучения:

```text
python -m training.finetune export --out data/training/run094
python -m training.finetune train --data data/training/run094 --confirm
python -m training.finetune evaluate --name chelsy-ft:0.9.4 --baseline <base>
python -m training.finetune register ...
```

Нельзя считать изменение имени модели доказательством обучения.
