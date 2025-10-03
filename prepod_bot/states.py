from aiogram.fsm.state import StatesGroup, State


class EditStudent(StatesGroup):
    waiting_new_username = State()
    waiting_new_fullname = State()


class EditTask(StatesGroup):
    waiting_new_text = State()


class StudentsList(StatesGroup):
    waiting_search_query = State()


class WorkGroups(StatesGroup):
    waiting_group_number = State()
    waiting_username = State()
    waiting_broadcast_group = State()
    waiting_broadcast_text = State()
    waiting_tasks_group = State()
    waiting_tasks_title = State()
    waiting_tasks_exam = State()
    waiting_tasks_ids = State()
    waiting_teacher_set = State()


class ReportSearch(StatesGroup):
    waiting_query = State()


class AddTeacherTask(StatesGroup):
    waiting_set_title = State()
    waiting_question_and_image = State()
    waiting_correct_answer = State()
