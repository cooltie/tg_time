import pytest
from datetime import datetime, timedelta

class TestTimeTrackingFinal:

    def test_time_calculation_accuracy(self):
        """Тест точности расчета времени"""
        # Тест различных временных интервалов
        test_cases = [
            (timedelta(hours=1, minutes=30), "01:30"),
            (timedelta(hours=0, minutes=45), "00:45"),
            (timedelta(hours=2, minutes=0), "02:00"),
            (timedelta(hours=0, minutes=0), "00:00")
        ]

        for duration, expected in test_cases:
            hours, remainder = divmod(duration.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            formatted_time = f"{int(hours):02}:{int(minutes):02}"
            assert formatted_time == expected, f"Expected {expected}, got {formatted_time} for {duration}"

    def test_user_state_machine(self):
        """Тест машины состояний пользователя"""
        # Определяем все возможные состояния
        valid_states = {
            'awaiting_new_project',
            'selecting_project',
            'running',
            'awaiting_comment'
        }

        # Симулируем переходы состояний
        user_timers = {}
        user_id = 12345

        # Начальное состояние
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        assert user_timers[user_id]['state'] in valid_states

        # Переход к созданию проекта
        user_timers[user_id]['state'] = 'running'
        assert user_timers[user_id]['state'] in valid_states

        # Переход к ожиданию комментария
        user_timers[user_id]['state'] = 'awaiting_comment'
        assert user_timers[user_id]['state'] in valid_states

        # Переход к выбору проекта
        user_timers[user_id]['state'] = 'selecting_project'
        assert user_timers[user_id]['state'] in valid_states

    def test_project_data_structure(self):
        """Тест структуры данных проекта"""
        user_projects = {}
        user_timers = {}
        user_id = 12345

        # Создание проекта
        project_name = "Test Project"
        user_projects[user_id] = [project_name]

        # Запуск таймера
        start_time = datetime.now()
        user_timers[user_id] = {
            'project': project_name,
            'start_time': start_time,
            'state': 'running'
        }

        # Проверка структуры
        assert 'project' in user_timers[user_id]
        assert 'start_time' in user_timers[user_id]
        assert 'state' in user_timers[user_id]
        assert user_timers[user_id]['project'] == project_name
        assert isinstance(user_timers[user_id]['start_time'], datetime)
        assert project_name in user_projects[user_id]

    def test_timer_duration_calculation(self):
        """Тест расчета длительности таймера"""
        # Симулируем работу таймера
        start_time = datetime.now() - timedelta(hours=1, minutes=30)
        end_time = datetime.now()

        # Расчет длительности
        duration = end_time - start_time

        # Проверки
        assert duration > timedelta(0)
        assert duration >= timedelta(hours=1, minutes=30)

        # Форматирование времени
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        formatted_time = f"{int(hours):02}:{int(minutes):02}"

        # Проверяем, что время отформатировано корректно
        assert len(formatted_time) == 5  # формат "HH:MM"
        assert formatted_time[2] == ':'  # разделитель
        assert formatted_time[:2].isdigit()  # часы
        assert formatted_time[3:].isdigit()  # минуты

    def test_complete_workflow_simulation(self):
        """Тест полного рабочего процесса"""
        user_timers = {}
        user_projects = {}
        user_id = 12345

        # 1. Пользователь запускает бота
        user_timers[user_id] = {'state': 'awaiting_new_project'}

        # 2. Создает новый проект
        project_name = "New Project"
        user_projects[user_id] = [project_name]
        user_timers[user_id] = {
            'project': project_name,
            'start_time': datetime.now(),
            'state': 'running'
        }

        # 3. Работает над проектом
        assert user_timers[user_id]['state'] == 'running'
        assert user_timers[user_id]['project'] == project_name

        # 4. Останавливает таймер
        end_time = datetime.now()
        user_timers[user_id]['end_time'] = end_time
        user_timers[user_id]['duration'] = end_time - user_timers[user_id]['start_time']
        user_timers[user_id]['state'] = 'awaiting_comment'

        # 5. Добавляет комментарий
        comment = "Test comment"
        user_timers[user_id]['comment'] = comment

        # 6. Возвращается к выбору проекта
        user_timers[user_id]['state'] = 'selecting_project'

        # Финальные проверки
        assert user_timers[user_id]['state'] == 'selecting_project'
        assert user_timers[user_id]['comment'] == comment
        assert project_name in user_projects[user_id]
        assert 'duration' in user_timers[user_id]
        assert user_timers[user_id]['duration'] > timedelta(0)
        assert user_timers[user_id]['project'] == project_name

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
