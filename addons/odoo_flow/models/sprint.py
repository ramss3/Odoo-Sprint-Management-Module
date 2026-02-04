from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta

class ProjectSprint(models.Model):
    _name = "project.sprint"
    _description = "Project Sprint"
    _order = "end_date desc, id desc"

    # ---- Constants ----
    DEFAULT_SPRINT_DAYS = 14
    MAX_SPRINT_DAYS = 28

    # --- Sprint fields ---
    name = fields.Char(required=True)

    project_id = fields.Many2one(
        "project.project",
        required=True,
        ondelete="cascade"
    )

    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)

    # “Intent” flag: False until user deviates from default end date
    end_date_manual = fields.Boolean(default=False)

    has_tasks = fields.Boolean(compute="_compute_has_tasks", store=True)

    # State mode: default auto. Manual is allowed through UI buttons
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

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    
    """Accepts datetime.date or 'YYYY-MM-DD' string; returns datetime.date or False."""
    def _to_date(self, value):
        if not value:
            return False
        return fields.Date.from_string(value) if isinstance(value, str) else value

    """start_date is datetime.date -> returns end time for the default sprint length"""
    def _default_end_date(self, start_date):
        return start_date + timedelta(days=self.DEFAULT_SPRINT_DAYS)

    # start is date or string -> returns 'YYYY-MM-DD'
    def _default_end_str(self, start):
        start_dt = self._to_date(start)
        return fields.Date.to_string(self._default_end_date(start_dt))

    # Project can't change once sprint has tasks or is active/done
    def _enforce_project_lock(self, vals):
        
        if "project_id" not in vals:
            return

        for sprint in self:
            if sprint.has_tasks:
                raise ValidationError("You cannot change the Project of the sprint once it has tasks.")
            if sprint.state in ("active", "done"):
                raise ValidationError("You cannot change the Project of the sprint once it is Active or Done.")
    
    # When sprint end_date changes, snap non-manual task deadlines to end_date
    def _sync_auto_task_deadlines_to_end(self):
        
        for sprint in self:
            if not sprint.end_date:
                continue
            tasks_to_update = sprint.task_ids.filtered(lambda t: not t.deadline_manual)
            if tasks_to_update:
                tasks_to_update.with_context(auto_deadline_sync=True).write({
                    "date_deadline": sprint.end_date,
                    "deadline_manual": False,
                })
    
    # If UI didn't send end_date_manual on write, infer it from current values
    def _infer_end_date_manual_if_missing(self):
        for sprint in self:
            if sprint.start_date and sprint.end_date:
                default_end = self._default_end_date(sprint.start_date)
                sprint.end_date_manual = (sprint.end_date != default_end)
        
    # Block deadline changes if any manual task deadline would be out of the sprint's window
    def _validate_task_deadlines_within_sprint(self):
        for sprint in self:
            if not sprint.start_date or not sprint.end_date:
                continue

            invalid = sprint.task_ids.filtered(lambda t:
                t.deadline_manual and t.date_deadline and (
                    t.date_deadline < sprint.start_date or t.date_deadline > sprint.end_date
                )
            )

            if invalid:
                sample = ", ".join(invalid[:5].mapped("name"))
                more = "" if len(invalid) <= 5 else f" (+{len(invalid) - 5} more)"
                raise ValidationError(_(
                "You cannot change the sprint dates because some tasks have "
                "manually set deadlines outside the sprint period.\n\n"
                "Sprint: %(s)s → %(e)s\n"
                "Tasks: %(sample)s%(more)s\n\n"
                "Update those task deadlines or remove them from the sprint.",
                s=sprint.start_date,
                e=sprint.end_date,
                sample=sample,
                more=more
            ))
    
    # -------------------------------------------------------------------------
    # Compute / inverse
    # -------------------------------------------------------------------------   

    def _compute_has_tasks(self):
        for s in self:
            s.has_tasks = bool(s.task_ids)

    #    When the task form opens, this method ensures the 'Selection' field 
    #    shows all tasks currently linked to the selected sprint's project.
    def _compute_task_select_ids(self):
        for sprint in self:
            sprint.task_select_ids = sprint.task_ids


    # This method runs when the user modifies task_select_ids in the UI.
    # When the user changes the selection, update the real task-sprint relationship
    # Odoo can call this for multiple records at once through the loop
    def _inverse_task_select_ids(self):
        for sprint in self:
            if not sprint.project_id:
                raise ValidationError("Please select a Project before adding tasks to the sprint.")

            to_add = sprint.task_select_ids - sprint.task_ids
            to_remove = sprint.task_ids - sprint.task_select_ids

            mismatched = to_add.filtered(lambda t: t.project_id != sprint.project_id)
            if mismatched:
                raise ValidationError("You can only add tasks from the project assigned to the sprint.")

            if to_add:
                to_add.write({"sprint_id": sprint.id})
            if to_remove:
                to_remove.write({"sprint_id": False})

            auto_tasks = to_add.filtered(lambda t: not t.deadline_manual and sprint.end_date)
            if auto_tasks:
                auto_tasks.with_context(auto_deadline_sync=True).write({
                    "date_deadline": sprint.end_date,
                    "deadline_manual": False,
                })
    
    # -------------------------------------------------------------------------
    # UI onchanges
    # -------------------------------------------------------------------------

    #  Sprint duration rules: Setting a fixed length of two weeks (14 days) for each sprint
    @api.onchange("start_date")
    def _onchange_start_date_set_default_end(self):
        for sprint in self:
            if not sprint.start_date:
                continue

            default_end = self._default_end_date(sprint.start_date)

            # Only auto-set end date if it's empty OR still auto-managed
            if not sprint.end_date or not sprint.end_date_manual:
                sprint.end_date = default_end
                sprint.end_date_manual = False

    # sprint end date is set to the default length unless user manually changes it
    @api.onchange("end_date")
    def _onchange_end_date_mark_manual(self):
        for sprint in self:
            if not sprint.start_date or not sprint.end_date:
                continue

            default_end = self._default_end_date(sprint.start_date)
            sprint.end_date_manual = (sprint.end_date != default_end)

    #    Sprint State updates immediately after dates are changed when in state_mode auto
    @api.onchange("start_date", "end_date", "state_mode", "state_manual")
    def _onchange_recompute_state(self):
        for sprint in self:
            sprint._compute_state()

    # -------------------------------------------------------------------------
    # Constrains
    # -------------------------------------------------------------------------
    
    #    Verifies if the tasks being assigned to the sprint are contained in the selected sprint's project
    #    If not, sends a validation error
    @api.constrains("project_id", "task_ids", "state")
    def _check_tasks_match_project(self):
        for sprint in self:
            if sprint.project_id and sprint.task_ids:
                mismatched = sprint.task_ids.filtered(lambda t: t.project_id != sprint.project_id)
                if mismatched:
                    raise ValidationError("All tasks in the sprint must belong to the assigned project in the same sprint.")
    
    # Ensure Start must be <= End and duration of the sprint does not exceed max set sprint days
    @api.constrains("start_date", "end_date")
    def _check_duration_and_order(self):
        for sprint in self:
            if sprint.start_date and sprint.end_date:
                if sprint.end_date < sprint.start_date:
                    raise ValidationError("Sprint end date cannot be before the start date.")

                duration_days = (sprint.end_date - sprint.start_date).days + 1
                if duration_days > self.MAX_SPRINT_DAYS:
                    max_days = self.MAX_SPRINT_DAYS
                    max_weeks = max_days // 7
                    raise ValidationError( f"Sprint duration cannot exceed {max_weeks} weeks ({max_days} days)." )
    
    # Past date rule for attemps to assigning sprints as planned/active with end dates prior to today
    @api.constrains("end_date", "state_mode", "state_manual")
    def _check_no_invalid_past_planned_active_sprint(self):
        today = fields.Date.context_today(self)
        for sprint in self:
            if not sprint.end_date:
                continue

            if sprint.state_mode == "manual" and sprint.end_date < today and sprint.state_manual in ("planned", "active"):
                raise ValidationError("A sprint whose end date is in the past cannot be set to Planned or Active.")
    
    #   Ensures no sprint assigned to the same project overlaps other by any means
    @api.constrains("project_id", "start_date", "end_date")
    def _check_no_overlap_sprints(self):
        for sprint in self:
            if not sprint.project_id or not sprint.start_date or not sprint.end_date:
                continue

            overlapping = self.search([
                ("project_id", "=", sprint.project_id.id),
                ("id", "!=", sprint.id),
                ("start_date", "<=", sprint.end_date),
                ("end_date", ">=", sprint.start_date),
            ], limit=1)

            if overlapping:
                raise ValidationError(_(
                    "This sprint (%(s)s → %(e)s) overlaps with '%(name)s' (%(os)s → %(oe)s). "
                    "Sprints in the same project cannot overlap.",
                    s=sprint.start_date, e=sprint.end_date,
                    name=overlapping.display_name, os=overlapping.start_date, oe=overlapping.end_date
                ))
    
    # -------------------------------------------------------------------------
    # State compute + cron + actions
    # -------------------------------------------------------------------------
                
    #    auto modifies sprint state according to the start and end date set by the user
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
    
    """
        Daily cron to keep stored state in sync with today's date
    """
    @api.model
    def cron_update_sprint_states(self):
        today = fields.Date.context_today(self)

        sprints = self.search([
            ("state_mode", "=", "auto"),
            ("start_date", "!=", False),
            ("end_date", "!=", False),
            ("state", "!=", "done")
        ])

        if sprints:
            sprints._compute_state()
                
    """
        Button actions to manually override the state of the sprint
    """
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

    # -------------------------------------------------------------------------
    # ORM overrides
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            start = vals.get("start_date")
            if not start:
                continue

            default_end = self._default_end_str(start)
            end = vals.get("end_date")
            manual = vals.get("end_date_manual")

            # If end not provided, auto-fill and keep manual False
            if not end:
                vals.update({"end_date": default_end, "end_date_manual": False})
            elif manual is None:
                end_str = fields.Date.to_string(end) if not isinstance(end, str) else end
                vals["end_date_manual"] = (end_str != default_end)
                    
        return super().create(vals_list)

    
    """
        Overriding write function as UI rules are not guarantees in Odoo. Therefore, It is created a business rule enforcement:
            - A sprint's assigned project cannot be changed once it contains tasks or once the sprint is Active or Done.

            This rule is being enforced at the Object-Relational Mapping (ORM) level to ensure data integrity across all entry points.
    """
    def write(self, vals):
        self._enforce_project_lock(vals)

        changing_dates = ("start_date" in vals) or ("end_date" in vals)

        # start_date changed and end_date not manually changed -> auto shift
        if "start_date" in vals and "end_date" not in vals and vals.get("start_date"):
            new_start = vals["start_date"]
            new_default_end = self._default_end_str(new_start)

            # Write per record to respect each sprint's manual flag
            ok = True
            for sprint in self:
                if sprint.end_date_manual:
                    ok = ok and super(ProjectSprint, sprint).write({"start_date": new_start})
                else:
                    ok = ok and super(ProjectSprint, sprint).write({
                        "start_date": new_start,
                        "end_date": new_default_end,
                        "end_date_manual": False,
                    })

            # Validate after write (rollback on error)
            self._validate_task_deadlines_within_sprint()
            return ok
        
        res = super().write(vals)

        # HARD RULE: if dates changed, block saving if any task deadline is now invalid
        if changing_dates:
            self._validate_task_deadlines_within_sprint()

        # If end_date changed explicitly, update non-manual task deadlines
        if "end_date" in vals:
            self._sync_auto_task_deadlines_to_end()
            if "end_date_manual" not in vals:
                self._infer_end_date_manual_if_missing()

        return res