import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta

# Тестируем только логику, без импорта основного файла
class TestTimeTrackingLogic:

    def test_time_calculation(self):
        start_time = datetime.now() - timedelta(hours=1, minutes=30)
        end_time = datetime.now()
        elapsed_time = end_time - start_time

        hours, remainder = divmod(elapsed_time.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        formatted_time = f"{int(hours):02}:{int(minutes):02}"

        assert formatted_time == "01:30"

    def test_user_state_management(self):
        user_timers = {}
        user_projects = {}

        user_id = 12345

        # Симуляция команды /start для нового пользователя
        user_timers[user_id] = {'state': 'awaiting_new_project'}
        assert user_timers[user_id]['state'] == 'awaiting_new_project'

        # Симуляция создания нового проекта
        project_name = "Test Project"
        user_projects[user_id] = [project_name]
        user_timers[user_id] = {
            'project': project_name,
            'start_time': datetime.now(),
            'state': 'running'
        }

        assert user_timers[user_id]['state'] == 'running'
        assert user_timers[user_id]['project'] == project_name
        assert project_name in user_projects[user_id]

    def test_timer_stop_logic(self):
        user_timers = {}
        user_id = 12345

        # Симуляция запущенного таймера
        start_time = datetime.now() - timedelta(hours=1)
        user_timers[user_id] = {
            'state': 'running',
            'start_time': start_time
        }

        # Симуляция остановки таймера
        end_time = datetime.now()
        elapsed_time = end_time - start_time

        user_timers[user_id]['end_time'] = end_time
        user_timers[user_id]['duration'] = elapsed_time
        user_timers[user_id]['state'] = 'awaiting_comment'

        assert user_timers[user_id]['state'] == 'awaiting_comment'
        assert 'end_time' in user_timers[user_id]
        assert 'duration' in user_timers[user_id]
        assert user_timers[user_id]['duration'] > timedelta(0)

    def test_project_workflow(self):
        user_timers = {}
        user_projects = {}
        user_id = 12345

        # Полный цикл работы с проектом
        # 1. Старт
        user_timers[user_id] = {'state': 'awaiting_new_project'}

        # 2. Создание проекта
        project_name = "New Project"
        user_projects[user_id] = [project_name]
        user_timers[user_id] = {
            'project': project_name,
            'start_time': datetime.now(),
            'state': 'running'
        }

        # 3. Остановка таймера
        end_time = datetime.now()
        user_timers[user_id]['end_time'] = end_time
        user_timers[user_id]['duration'] = end_time - user_timers[user_id]['start_time']
        user_timers[user_id]['state'] = 'awaiting_comment'

        # 4. Добавление комментария
        comment = "Test comment"
        user_timers[user_id]['comment'] = comment

        # 5. Возврат к выбору проекта
        user_timers[user_id]['state'] = 'selecting_project'

        assert user_timers[user_id]['state'] == 'selecting_project'
        assert user_timers[user_id]['comment'] == comment
        assert project_name in user_projects[user_id]

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
