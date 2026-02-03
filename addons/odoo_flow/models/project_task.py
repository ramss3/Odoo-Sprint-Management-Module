from odoo import models, fields, api
from odoo.exceptions import ValidationError

class ProjectTask(models.Model):
    _inherit = "project.task"

    from_sprint = fields.Boolean(compute="_compute_from_sprint", store=False)

    def _compute_from_sprint(self):
        flag = bool(self.env.context.get("from_sprint"))
        for rec in self:
            rec.from_sprint = flag

    sprint_id = fields.Many2one(
        "project.sprint",
        string="Sprint"
    )

    @api.constrains("sprint_id", "date_deadline", "project_id")
    def _check_sprint_deadline_and_project(self):
        for task in self:
            if not task.sprint_id:
                continue

            # Ensure task project matches sprint project
            if task.project_id and task.sprint_id.project_id and task.project_id != task.sprint_id.project_id:
                raise ValidationError(
                    "A task can only be assigned to a sprint belonging to the same project.\n\n"
                    "Please update either the task's project or the assigned sprint to ensure they match."
                )

            # Ensure task deadline does not exceed sprint end date
            if task.date_deadline and task.sprint_id.end_date and task.date_deadline > task.sprint_id.end_date:
                raise ValidationError(
                    f'The task "{task.name}" deadline ({task.date_deadline}) falls outside the sprint period.\n\n'
                    f"Please set a deadline on or before the sprint's end date ({task.sprint_id.end_date})."
                )
            
    # If user picks a sprint and task has no deadline so far, suggest sprint end date
    @api.onchange("sprint_id")
    def _onchange_sprint_id(self):
        for task in self:
            if task.sprint_id and not task.date_deadline and task.sprint_id.end_date:
                task.date_deadline = task.sprint_id.end_date
