import { useEffect, useState, type FormEvent } from "react";
import {
  changePassword,
  createUser,
  deleteUser,
  getMe,
  listUsers,
} from "../api";
import type { User } from "../types";

export default function AccountPage() {
  const [me, setMe] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);

  // Password change
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwMsg, setPwMsg] = useState({ text: "", ok: false });

  // New user
  const [newUsername, setNewUsername] = useState("");
  const [newUserPw, setNewUserPw] = useState("");
  const [newRole, setNewRole] = useState("user");
  const [userMsg, setUserMsg] = useState({ text: "", ok: false });

  useEffect(() => {
    getMe().then(setMe);
    loadUsers();
  }, []);

  async function loadUsers() {
    try {
      const data = await listUsers();
      setUsers(data.users ?? []);
    } catch {}
  }

  async function handlePasswordChange(e: FormEvent) {
    e.preventDefault();
    setPwMsg({ text: "", ok: false });
    try {
      await changePassword(currentPw, newPw);
      setPwMsg({ text: "Password changed.", ok: true });
      setCurrentPw("");
      setNewPw("");
    } catch (err) {
      setPwMsg({
        text: err instanceof Error ? err.message : "Failed",
        ok: false,
      });
    }
  }

  async function handleCreateUser(e: FormEvent) {
    e.preventDefault();
    setUserMsg({ text: "", ok: false });
    try {
      await createUser(newUsername, newUserPw, newRole);
      setUserMsg({ text: `User "${newUsername}" created.`, ok: true });
      setNewUsername("");
      setNewUserPw("");
      setNewRole("user");
      loadUsers();
    } catch (err) {
      setUserMsg({
        text: err instanceof Error ? err.message : "Failed",
        ok: false,
      });
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteUser(id);
      setUsers((prev) => prev.filter((u) => u.id !== id));
    } catch {}
  }

  const isSuperadmin = me?.role === "superadmin";

  return (
    <div className="space-y-8 max-w-2xl">
      <h1 className="text-2xl font-bold text-white">Account Settings</h1>

      {/* Profile */}
      <section className="bg-gray-900/60 rounded-xl border border-gray-700 p-5 space-y-1">
        <h2 className="text-lg font-semibold mb-2">My Account</h2>
        <p className="text-gray-300">
          Username: <span className="text-white font-medium">{me?.username}</span>
        </p>
        <p className="text-gray-300">
          Role:{" "}
          <span className="px-1.5 py-0.5 rounded bg-gray-800 text-xs text-gray-200 uppercase">
            {me?.role}
          </span>
        </p>
      </section>

      {/* Password Change */}
      <section className="bg-gray-900/60 rounded-xl border border-gray-700 p-5 space-y-4">
        <h3 className="font-semibold">Change Password</h3>
        <form onSubmit={handlePasswordChange} className="space-y-3">
          <input
            type="password"
            placeholder="Current password"
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
            required
            className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
          />
          <input
            type="password"
            placeholder="New password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            required
            minLength={4}
            className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
          />
          {pwMsg.text && (
            <p className={pwMsg.ok ? "text-emerald-400 text-sm" : "text-red-400 text-sm"}>
              {pwMsg.text}
            </p>
          )}
          <button
            type="submit"
            className="px-4 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-sm font-medium transition-colors"
          >
            Update Password
          </button>
        </form>
      </section>

      {/* Superadmin: User Management */}
      {isSuperadmin && (
        <section className="bg-gray-900/60 rounded-xl border border-gray-700 p-5 space-y-5">
          <h3 className="font-semibold">User Management</h3>

          {/* Create user */}
          <form onSubmit={handleCreateUser} className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <input
                placeholder="Username"
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                required
                className="rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              />
              <input
                placeholder="Password"
                type="password"
                value={newUserPw}
                onChange={(e) => setNewUserPw(e.target.value)}
                required
                minLength={4}
                className="rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              />
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                className="rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-gray-200"
              >
                <option value="user">User</option>
                <option value="superadmin">Superadmin</option>
              </select>
            </div>
            {userMsg.text && (
              <p className={userMsg.ok ? "text-emerald-400 text-sm" : "text-red-400 text-sm"}>
                {userMsg.text}
              </p>
            )}
            <button
              type="submit"
              className="px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm font-medium transition-colors"
            >
              Create User
            </button>
          </form>

          {/* User list */}
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
                <th className="pb-2 pr-3">ID</th>
                <th className="pb-2 pr-3">Username</th>
                <th className="pb-2 pr-3">Role</th>
                <th className="pb-2 w-16">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-gray-900/50">
                  <td className="py-2 pr-3 text-gray-500">{u.id}</td>
                  <td className="py-2 pr-3 text-gray-200">{u.username}</td>
                  <td className="py-2 pr-3">
                    <span className="px-1.5 py-0.5 rounded bg-gray-800 text-xs text-gray-300 uppercase">
                      {u.role}
                    </span>
                  </td>
                  <td className="py-2">
                    {u.id !== me?.id && (
                      <button
                        onClick={() => handleDelete(u.id)}
                        className="text-xs text-gray-500 hover:text-red-400"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
