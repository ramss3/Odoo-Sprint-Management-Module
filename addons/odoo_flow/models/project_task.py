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

    # If user manually changes date_deadline the deadline_manual becomes true
    deadline_manual = fields.Boolean(default=False)

    # Helper to hold the sprint's deadline
    sprint_default_deadline = fields.Date(
        compute="_compute_sprint_default_deadline",
        store=False,
    )

    @api.depends("sprint_id", "sprint_id.end_date")
    def _compute_sprint_default_deadline(self):
        for task in self:
            task.sprint_default_deadline = task.sprint_id.end_date if task.sprint_id else False

    @api.constrains("sprint_id", "date_deadline", "project_id")
    def _check_sprint_deadline_and_project(self):
        for task in self:
            if not task.sprint_id:
                continue
                
            sprint = task.sprint_id

            # Ensure task project matches sprint project
            if task.project_id and task.sprint_id.project_id and task.project_id != sprint.project_id:
                raise ValidationError(
                    "A task can only be assigned to a sprint belonging to the same project.\n\n"
                    "Please update either the task's project or the assigned sprint to ensure they match."
                )

            # Ensure deadline is not before sprint start
            if sprint.start_date and task.date_deadline < sprint.start_date:
                raise ValidationError(
                    f'The task "{task.name}" deadline ({task.date_deadline}) is before the sprint start date ({sprint.start_date}).\n\n'
                    "Please set a deadline within the sprint period."
                )

            # Ensure task deadline does not exceed sprint end date
            if task.date_deadline and task.sprint_id.end_date and task.date_deadline > task.sprint_id.end_date:
                raise ValidationError(
                    f'The task "{task.name}" deadline ({task.date_deadline}) falls outside the sprint period.\n\n'
                    f"Please set a deadline on or before the sprint's end date ({task.sprint_id.end_date})."
                )
            
    # UI: when sprint changes, auto-set deadline unless user has manually pinned it
    @api.onchange("sprint_id")
    def _onchange_sprint_id(self):
        for task in self:
            if not task.sprint_id:
                continue
            if task.sprint_id.end_date and (not task.deadline_manual or not task.date_deadline):
                task.date_deadline = task.sprint_id.end_date
                task.deadline_manual = False
    
    # UI: if user edits date_deadline away from sprint default, mark as manual
    @api.onchange("date_deadline", "sprint_id")
    def _onchange_date_deadline_mark_manual(self):
        for task in self:
            if not task.sprint_id:
                continue
            default = task.sprint_default_deadline
            # If user changed it (including clearing it), treat as manual override
            if task.date_deadline != default:
                task.deadline_manual = True
            else:
                task.deadline_manual = False
    
    @api.model_create_multi
    def create(self, vals_list):
        Sprint = self.env["project.sprint"]
        for vals in vals_list:
            sprint_id = vals.get("sprint_id")
            if sprint_id:
                sprint = Sprint.browse(sprint_id)
                # If no deadline provided, inherit sprint end_date
                if not vals.get("date_deadline") and sprint.end_date:
                    vals["date_deadline"] = sprint.end_date
                # If deadline equals sprint end_date => not manual
                if vals.get("date_deadline") and sprint.end_date and vals["date_deadline"] == sprint.end_date:
                    vals["deadline_manual"] = False
        return super().create(vals_list)

    def write(self, vals):
        auto_sync = self.env.context.get("auto_deadline_sync")

        res = super().write(vals)

        # Only determine manual flag for real user writes (not our sync writes)
        if not auto_sync:
            # If either sprint_id or date_deadline changed, re-evaluate manual flag
            if "sprint_id" in vals or "date_deadline" in vals:
                for task in self:
                    if not task.sprint_id or not task.sprint_id.end_date:
                        continue
                    if task.date_deadline == task.sprint_id.end_date:
                        if task.deadline_manual:
                            task.with_context(auto_deadline_sync=True).write({"deadline_manual": False})
                    else:
                        if not task.deadline_manual:
                            task.with_context(auto_deadline_sync=True).write({"deadline_manual": True})

        return res
