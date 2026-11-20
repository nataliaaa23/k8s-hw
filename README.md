# Управление ресурсами в Kubernetes: пары навыков вакансий 1С

Практическая работа № 5 по дисциплине «Инженерия данных».

Выполнила: Андреева Наталия Леонидовна, группа J3310.

## Что сделано

Программа подсчёта пар навыков из практической работы № 3 (вариант 1: «Программист, разработчик на 1С») упакована в образ и запущена в кластере Kubernetes (minikube) как задание с заявками и пределами ресурсов. Получена остановка по памяти (OOMKilled), предел подобран по измеренному пику. Хранилище RustFS перенесено внутрь кластера, расчёт выполнен параллельными задачами по частям файла. Показаны ожидание при нехватке процессора, вытеснение задачи с низким приоритетом задачей с высоким и действие квоты пространства имён. Итоговый файл пар побайтно совпал с результатом практической работы № 3.

## Структура

- `Dockerfile` — образ hh-pairs:1.0
- `app/pairs.py` — программа (режимы run, plan, part, merge)
- `k8s/00-namespace.yaml` — пространство имён lab
- `k8s/10-job-oom.yaml` — предел памяти 100 Mi, OOMKilled
- `k8s/20-job-measure.yaml` — измерение пика (предел 512 Mi)
- `k8s/30-job-below.yaml` — предел 144 Mi ниже пика, OOMKilled
- `k8s/40-job-tuned.yaml` — подобранный предел 208 Mi
- `k8s/50-rustfs.yaml` — RustFS в кластере (Deployment, PVC, Service)
- `k8s/60-job-incluster.yaml` — расчёт с хранилищем внутри кластера
- `k8s/70-job-plan.yaml`, `k8s/80-job-parts.yaml`, `k8s/90-job-merge.yaml` — параллельный расчёт
- `k8s/100-pod-cpu-a.yaml`, `k8s/110-pod-cpu-b.yaml` — ожидание при нехватке процессора
- `k8s/120-priority.yaml`, `k8s/130-low-prio.yaml`, `k8s/140-pod-high.yaml` — приоритеты и вытеснение
- `k8s/150-quota.yaml`, `k8s/160-pod-big.yaml`, `k8s/170-job-parts-quota.yaml` — квота
- `logs/` — журналы запусков
- `results/` — итоговый файл пар и топ-10
- `report/` — отчёт

## Запуск

Нужны Docker Desktop, minikube, kubectl и запущенный RustFS из практической работы № 2 с бакетом hh-lake.

```
minikube start --driver=docker --cpus=4 --memory=5500
minikube addons enable metrics-server
docker build -t hh-pairs:1.0 .
minikube image load hh-pairs:1.0
minikube image load rustfs/rustfs:latest
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/10-job-oom.yaml
kubectl apply -f k8s/20-job-measure.yaml
kubectl apply -f k8s/30-job-below.yaml
kubectl apply -f k8s/40-job-tuned.yaml
kubectl apply -f k8s/50-rustfs.yaml
```

После загрузки объекта raw/it_vacancies_2024.csv в бакет hh-lake внутри кластера (через `kubectl port-forward -n lab svc/rustfs 9200:9000`):

```
kubectl apply -f k8s/60-job-incluster.yaml
kubectl apply -f k8s/70-job-plan.yaml
kubectl apply -f k8s/80-job-parts.yaml
kubectl apply -f k8s/90-job-merge.yaml
```

Опыты с планированием:

```
kubectl apply -f k8s/100-pod-cpu-a.yaml
kubectl apply -f k8s/110-pod-cpu-b.yaml
kubectl apply -f k8s/120-priority.yaml
kubectl apply -f k8s/130-low-prio.yaml
kubectl apply -f k8s/140-pod-high.yaml
kubectl apply -f k8s/150-quota.yaml
kubectl apply -f k8s/160-pod-big.yaml
kubectl apply -f k8s/170-job-parts-quota.yaml
```

## Основные результаты

| Показатель | Значение |
| --- | --- |
| Записей / вакансий варианта / с навыками | 229 388 / 20 953 / 13 452 |
| Уникальных пар навыков | 32 298 |
| Пик памяти программы | 162,1 МиБ |
| Предел памяти (пик × 1,25, округление до 16 Mi) | 208 Mi, заявка 160 Mi |
| Предел 100 Mi и 144 Mi | OOMKilled, код 137 |
| SHA-256 файла пар | 7c106b955e553c96969030094dc79eef74dcffbee71d92d34abcf33ddefcd8af |
| Совпадение с практической работой № 3 | полное (fc: различий нет) |
| Расчёт в одном поде / параллельный Job (12 частей, 4 пода) | 11,5 с / 15 с |

Топ-10 пар навыков:

| № | Вакансий | Пара навыков |
| --- | --- | --- |
| 1 | 4 307 | 1с программирование + 1с: предприятие 8 |
| 2 | 3 063 | 1с программирование + 1с: бухгалтерия |
| 3 | 2 376 | 1с программирование + 1с: управление торговлей |
| 4 | 2 324 | 1с программирование + обновление конфигурации 1с |
| 5 | 2 137 | 1с: бухгалтерия + 1с: предприятие 8 |
| 6 | 2 021 | 1с программирование + erp-системы на базе 1с |
| 7 | 1 803 | 1с программирование + 1с: документооборот |
| 8 | 1 758 | 1с программирование + 1с: зарплата и управление персоналом |
| 9 | 1 587 | 1с: предприятие 8 + 1с: управление торговлей |
| 10 | 1 534 | 1с: бухгалтерия + 1с: управление торговлей |

Подробности, скриншоты и ответы на вопросы о соответствии YARN, Mesos и Kubernetes — в отчёте `report/otchet_pr5.pdf`.
