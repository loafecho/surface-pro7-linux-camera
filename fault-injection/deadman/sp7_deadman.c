// SPDX-License-Identifier: GPL-2.0
/*
 * sp7_deadman - restart/power-off deadman timer for the Surface Pro 7.
 *
 * Every standard watchdog driver calls watchdog_stop_on_reboot(), and the
 * reboot notifier chain runs before device_shutdown(), so nothing recovers a
 * hang inside a driver's shutdown/remove path. This module registers a
 * highest-priority reboot notifier that arms a timer on restart, power-off
 * and halt. If the system is still running when the timer expires, it dumps
 * the blocked (D-state) tasks and either panics (the panic dump goes to
 * pstore, then panic_timeout restarts the machine) or calls
 * emergency_restart() directly. Once armed nothing disarms it.
 *
 * Parameters (runtime-writable via /sys/module/sp7_deadman/parameters/):
 *   timeout_s  seconds from the reboot notifier to firing (default 90)
 *   mode       0 = off, 1 = panic (record in pstore), 2 = emergency_restart
 *   test_hang  test only: if 1, a dummy device's .shutdown sleeps forever,
 *              simulating a driver hung in device_shutdown()
 */
#include <linux/module.h>
#include <linux/reboot.h>
#include <linux/timer.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/sched/debug.h>
#include <linux/nmi.h>
#include <linux/delay.h>
#include <linux/platform_device.h>
#include <linux/panic.h>

static unsigned int timeout_s = 90;
module_param(timeout_s, uint, 0644);
MODULE_PARM_DESC(timeout_s, "Seconds after a restart/power-off starts before firing");

static int mode = 1;
module_param(mode, int, 0644);
MODULE_PARM_DESC(mode, "0=off 1=panic(pstore record) 2=emergency_restart");

static bool test_hang;
module_param(test_hang, bool, 0644);
MODULE_PARM_DESC(test_hang, "TEST ONLY: hang forever in device_shutdown()");

static struct timer_list deadman_timer;
static unsigned long armed_action;
static atomic_t armed = ATOMIC_INIT(0);

static const char *action_name(unsigned long a)
{
	switch (a) {
	case SYS_RESTART: return "restart";
	case SYS_HALT: return "halt";
	case SYS_POWER_OFF: return "power-off";
	default: return "unknown";
	}
}

/*
 * Like sysrq-w, but handle_sysrq() honours kernel.sysrq even from kernel
 * callers on this kernel (mask 176 disables it), so walk the tasks here.
 */
static void deadman_show_blocked(void)
{
	struct task_struct *g, *p;
	unsigned int n = 0, s;

	pr_emerg("sp7_deadman: blocked tasks:\n");
	rcu_read_lock();
	for_each_process_thread(g, p) {
		s = READ_ONCE(p->__state);
		if (!(s & TASK_UNINTERRUPTIBLE) || (s & TASK_NOLOAD))
			continue;
		touch_nmi_watchdog();
		sched_show_task(p);
		if (++n >= 40) {
			pr_emerg("sp7_deadman: (stopped after 40 tasks)\n");
			break;
		}
	}
	rcu_read_unlock();
	pr_emerg("sp7_deadman: %u blocked tasks shown\n", n);
}

static void deadman_fire(struct timer_list *t)
{
	pr_emerg("sp7_deadman: FIRED: %s still not done after %u s (mode %d)\n",
		 action_name(armed_action), timeout_s, mode);
	/* Stacks of every task in D state, PID 1 included. */
	deadman_show_blocked();
	if (mode == 2) {
		pr_emerg("sp7_deadman: SAFETY-NET EVENT: emergency_restart\n");
		emergency_restart();
		return;
	}
	if (panic_timeout <= 0)
		panic_timeout = 10;
	panic("sp7_deadman: SAFETY-NET EVENT: %s stuck for %u s",
	      action_name(armed_action), timeout_s);
}

static int deadman_reboot_notify(struct notifier_block *nb,
				 unsigned long action, void *data)
{
	if (mode <= 0 || timeout_s == 0)
		return NOTIFY_DONE;
	if (atomic_xchg(&armed, 1))
		return NOTIFY_DONE;
	armed_action = action;
	mod_timer(&deadman_timer, jiffies + (unsigned long)timeout_s * HZ);
	pr_emerg("sp7_deadman: armed for %s, fires in %u s (mode %d)\n",
		 action_name(action), timeout_s, mode);
	return NOTIFY_DONE;
}

static struct notifier_block deadman_nb = {
	.notifier_call = deadman_reboot_notify,
	.priority = INT_MAX,
};

static void deadman_dev_shutdown(struct platform_device *pdev)
{
	if (!test_hang)
		return;
	pr_emerg("sp7_deadman: TEST HANG in device_shutdown(), sleeping forever\n");
	for (;;)
		ssleep(60);
}

static struct platform_driver deadman_driver = {
	.shutdown = deadman_dev_shutdown,
	.driver = { .name = "sp7_deadman" },
};

static struct platform_device *deadman_pdev;

static int __init deadman_init(void)
{
	int ret;

	timer_setup(&deadman_timer, deadman_fire, 0);
	ret = platform_driver_register(&deadman_driver);
	if (ret)
		return ret;
	deadman_pdev = platform_device_register_simple("sp7_deadman", -1, NULL, 0);
	if (IS_ERR(deadman_pdev)) {
		platform_driver_unregister(&deadman_driver);
		return PTR_ERR(deadman_pdev);
	}
	ret = register_reboot_notifier(&deadman_nb);
	if (ret) {
		platform_device_unregister(deadman_pdev);
		platform_driver_unregister(&deadman_driver);
		return ret;
	}
	pr_info("sp7_deadman: loaded, timeout %u s, mode %d\n", timeout_s, mode);
	return 0;
}

static void __exit deadman_exit(void)
{
	unregister_reboot_notifier(&deadman_nb);
	timer_delete_sync(&deadman_timer);
	platform_device_unregister(deadman_pdev);
	platform_driver_unregister(&deadman_driver);
}

module_init(deadman_init);
module_exit(deadman_exit);
MODULE_DESCRIPTION("Restart/power-off deadman timer (Surface Pro 7)");
MODULE_LICENSE("GPL");
