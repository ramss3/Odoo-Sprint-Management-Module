from odoo import models, fields, api, _
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

    # -------------------------------------------------------------------------
    # UI helpers
    # -------------------------------------------------------------------------

    @api.onchange("name", "sprint_id", "project_id")
    def _onchange_warn_duplicate_task_name_in_sprint(self):
        for task in self:
            name = (task.name or "").strip()
            if not name or not task.sprint_id:
                continue
            

            duplicates_in_sprint = [
                ("name", "=", name),
                ("sprint_id", "=", task.sprint_id.id),
            ]

            # Only exclude itself if it has a real DB id (int)
            if isinstance(task.id, int):
                duplicates_in_sprint.append(("id", "!=", task.id))
            
            if self.env["project.task"].search_count(duplicates_in_sprint):
                return {
                    "warning": {
                        "title": _("Possible duplicate task name"),
                        "message": _(
                            "Another task with the name '%(name)s' already exists in this sprint.\n\n"
                            "This is allowed, but it may cause confusion on the sprint board. ",
                            name=name,
                        ),
                    }
                }
    
    # when sprint changes, auto-set deadline unless user has manually pinned it
    @api.onchange("sprint_id")
    def _onchange_sprint_id(self):
        for task in self:
            if task.sprint_id and task.sprint_id.end_date:
                task.date_deadline = task.sprint_id.end_date
                task.deadline_manual = False
    
    # If user edits task date_deadline, mark as manual
    @api.onchange("date_deadline")
    def _onchange_date_deadline_mark_manual(self):
        for task in self:
            if not task.sprint_id:
                continue
            task.deadline_manual = (task.date_deadline != task.sprint_id.end_date)
    
    # -------------------------------------------------------------------------
    # Business rules (ORM)
    # -------------------------------------------------------------------------

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
            if task.date_deadline and sprint.start_date and task.date_deadline < sprint.start_date:
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
            
    
    @api.model_create_multi
    def create(self, vals_list):
        Sprint = self.env["project.sprint"]
        for vals in vals_list:
            sprint_id = vals.get("sprint_id")
            if not sprint_id:
                continue

            sprint = Sprint.browse(sprint_id)
            if not sprint.exists():
                continue

            if not vals.get("date_deadline"):
                vals["date_deadline"] = sprint.end_date
                vals["deadline_manual"] = False
            else:
                vals["deadline_manual"] = (vals["date_deadline"] != sprint.end_date)

        return super().create(vals_list)

    def write(self, vals):
        auto_sync = self.env.context.get("auto_deadline_sync")

        # Handle sprint moves before super().write() (constraints)
        if (not auto_sync) and ("sprint_id" in vals):
            Sprint = self.env["project.sprint"]
            new_sprint = Sprint.browse(vals["sprint_id"]) if vals.get("sprint_id") else Sprint
        
            ok = True
            for task in self:
                v = dict(vals)

                # If removing sprint, just write normally (constraint will skip)
                if not v.get("sprint_id"):
                    ok = ok and super(ProjectTask, task).write(v)
                    continue

                # Force sprint end date as deadline and reset manual flag (always)
                if new_sprint.end_date:
                    v["date_deadline"] = new_sprint.end_date
                    v["deadline_manual"] = False

                ok = ok and super(ProjectTask, task).write(v)

            return ok

        # if user updates date_deadline, set manual flag in the same write
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

        return super().write(vals)