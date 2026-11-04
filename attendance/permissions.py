"""Object-level checks for attendance actions."""
from employee.models import EmployeeWorkInformation


def can_manage_attendance(user, attendance):
    employee = getattr(user, "employee_get", None)
    if not employee or employee.pk == attendance.employee_id_id:
        return False
    if user.has_perm("attendance.change_attendance"):
        return True
    return EmployeeWorkInformation.objects.filter(
        employee_id=attendance.employee_id, reporting_manager_id=employee
    ).exists()


def can_view_attendance(user, attendance):
    employee = getattr(user, "employee_get", None)
    return bool(employee and (employee.pk == attendance.employee_id_id or
                user.has_perm("attendance.view_attendance") or can_manage_attendance(user, attendance)))
