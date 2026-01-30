from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import timedelta

class ProjectSprint(models.Model):
    _name = "project.sprint"
    _description = "Project Sprint"
    _order = "end_date desc, id desc"

    name = fields.Char(required=True)

    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade"
    )

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)

    # State mode: default auto. Manual is allowed via buttons
    state_mode = fields.Selection(
        [("auto", "Auto"), ("manual", "Manual")],
        default="auto",
        required=True,
    )

    state_manual = fields.Selection(
        [("planned", "Planned"),
            ("active", "Active"),
            ("done", "Done"),],
            default="planned",
            required=True,
    )

    """ Automatically determine whether a sprint is currently being planned, active, 
        or finished based on the current date using function"_compute_state" when will automatically store in the database
    """
    state = fields.Selection(
        [
            ("planned", "Planned"),
            ("active", "Active"),
            ("done", "Done")
        ],
        compute="_compute_state",
        store=True,
        readonly=True,
    )

    task_ids = fields.One2many(
        "project.task",
        "sprint_id",
        string="Tasks"
    )

    #   Dropdown menu allowing user to select already created tasks for the selected project. It does not direcly store in the database
    task_select_ids = fields.Many2many(
        "project.task",
        string="Existing Tasks",
        compute="_compute_task_select_ids",
        inverse="_inverse_task_select_ids",
    )

    """
        When the form opens, this method ensures the 'Selection' field 
        shows all tasks currently linked to the selected project.
    """
    def _compute_task_select_ids(self):
        for sprint in self:
            sprint.task_select_ids = sprint.task_ids

    # assign sprint to selected tasks, and unassign from removed ones
    def _inverse_task_select_ids(self):

        for sprint in self:
            if not sprint.project_id:
                raise ValidationError("Please select a Project before adding tasks to the sprint.")
    
            to_add = sprint.task_select_ids - sprint.task_ids
            to_remove = sprint.task_ids - sprint.task_select_ids

            mismatched = to_add.filtered(lambda t: t.project_id != sprint.project_id)
            if mismatched:
                raise ValidationError("You can only add tasks from the project assigned to the sprint.")

            to_add.write({"sprint_id": sprint.id})
            to_remove.write({"sprint_id": False})

    # Prevent chaning project once spring has tasks or once sprint is not planned
    @api.constrains("project_id", "task_ids", "state")
    def _check_tasks_match_project(self):
        for sprint in self:
            if sprint.project_id and sprint.task_ids:
                mismatched = sprint.task_ids.filtered(lambda t: t.project_id != sprint.project_id)
                if mismatched:
                    raise ValidationError("All tasks in the sprint must belong to the assigned project in the same sprint.")

    # Sprint duration rules
    @api.onchange("start_date")
    def _onchange_start_date_set_default_end(self):
        # setting the default sprint duration to 14 days (2 weeks period)
        for sprint in self:
            if sprint.start_date and not sprint.end_date:
                sprint.end_date = sprint.start_date + timedelta(days=14)
    
    # State updates immediately after dates are changed when in state_mode auto
    @api.onchange("start_date", "end_date", "state_mode", "state_manual")
    def _onchange_recompute_state(self):
        for sprint in self:
            sprint._compute_state()
    
    @api.constrains("start_date", "end_date")
    def _check_duration_and_order(self):
        # Start must be <= End and sprint duration must be at most 4 weeks (28 days)
        for sprint in self:
            if sprint.start_date and sprint.end_date:
                if sprint.end_date < sprint.start_date:
                    raise ValidationError("Sprint end date cannot be before the start date.")

                duration_days = (sprint.end_date - sprint.start_date).days + 1
                if duration_days > 28:
                    raise ValidationError("Sprint duration cannot exceed 4 weeks (28 days).")
                
    # auto assign sprint state according to the start and end date defined while creating the sprint    
    @api.depends("start_date", "end_date", "state_mode", "state_manual")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for sprint in self:
            if sprint.state_mode == "manual":
                sprint.state = sprint.state_manual
                continue
            
            # auto state assignment
            if sprint.start_date and today < sprint.start_date:
                sprint.state = "planned"
            elif sprint.start_date and sprint.end_date and sprint.start_date <= today <= sprint.end_date:
                sprint.state = "active"
            elif sprint.end_date and today > sprint.end_date:
                sprint.state = "done"
            else:
                # fallback if dates incomplete
                sprint.state = "planned"
    
    # Past date rule for attemps to assigning sprints as planned/active with end dates prior to today
    # Verificar se aqui é necessario validar a start date uma vez que so a end date interessa para a constrain
    @api.constrains("start_date", "end_date", "state_mode", "state_manual")
    def _check_no_invalid_past_planned_active_sprint(self):
        today = fields.Date.context_today(self)
        for sprint in self:
            if not sprint.start_date or not sprint.end_date:
                continue
                
            if sprint.state_mode == "manual" and sprint.end_date < today and sprint.state_manual in ("planned", "active"):
                raise ValidationError("A sprint whose end date is in the past cannot be set to Planned or Active.")
    
    # One active sprint per project
    @api.constrains("state", "project_id")
    def _check_if_project_already_has_active_sprint(self):
        for sprint in self:
            if sprint.state == "active":
                other_active = self.search_count([
                    ("project_id", "=", sprint.project_id.id),
                    ("state", "=", "active"),
                    ("id", "!=", sprint.id)
                ])
                if other_active:
                    raise ValidationError("Only one active sprint is allowed per project.")
                
    # Button actions (manual override)
    def action_set_auto(self):
        self.write({"state_mode": "auto"})
        self._compute_state()
        return True

    def action_set_planned(self):
        self.write({"state_mode": "manual", "state_manual": "planned"})
        return True

    def action_set_active(self):
        self.write({"state_mode": "manual", "state_manual": "active"})
        return True
    
    def action_set_done(self):
        self.write({"state_mode": "manual", "state_manual": "done"})
        return True
    
    """
        Overriding write function as UI rules are not guarantees in Odoo. Therefore, It is created a business rule enforcement:
            - A sprint's assigned project cannot be changed once it contains tasks or once the sprint is Active or Done.

            This rule is being enforced at the Object-Relational Mapping (ORM) level to ensure data integrity across all entry points.
    """
    def write(self, vals):
        if "project_id" in vals:
            Task = self.env["project.task"]
            for sprint in self:
                # Check in DB
                has_tasks = Task.search_count([("sprint_id", "=", sprint.id)]) > 0
                if has_tasks:
                    raise ValidationError("You cannot change the Project of the sprint once it has tasks.")
                if sprint.state in ("active", "done"):
                    raise ValidationError("You cannot change the Project of the sprint once it is Active or Done.")
        return super().write(vals)