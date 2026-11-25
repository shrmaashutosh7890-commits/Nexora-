document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  const API = '/api';
  let csrfToken = '';
  let isAuthenticated = false;
  let leads = [];
  let analyticsRequestId = 0;

  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];

  const loginScreen = $('#adminLogin');
  const loginForm = $('#adminLoginForm');
  const loginButton = $('#adminLoginButton');
  const loginError = $('#adminLoginError');
  const emailInput = $('#adminEmail');
  const passwordInput = $('#adminPassword');
  const dashboard = $('#dashboardApp');
  const logoutButton = $('#adminLogout');
  const leadModal = $('#leadModal');
  const leadForm = $('#leadForm');

  if (!loginScreen || !loginForm || !dashboard) {
    console.error('Nexora: Required login elements are missing.');
    return;
  }

  const escapeHTML = value =>
    String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[character]);

  function setText(selector, value) {
    const element = $(selector);
    if (element) element.textContent = value;
  }

  function localTodayISO() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function isConverted(lead) {
    return String(lead.status || '').toLowerCase() === 'converted';
  }

  function getFollowUpStats(items = leads) {
    const today = localTodayISO();
    let overdue = 0;
    let dueToday = 0;
    let upcoming = 0;

    items.forEach(lead => {
      const followUpDate = String(lead.follow_up_date || '').slice(0, 10);

      if (!followUpDate || isConverted(lead)) return;

      if (followUpDate < today) overdue++;
      else if (followUpDate === today) dueToday++;
      else upcoming++;
    });

    return {
      overdue,
      today: dueToday,
      due: overdue + dueToday,
      upcoming
    };
  }

  function formatDate(value) {
    const dateString = String(value || '').slice(0, 10);
    if (!dateString) return '—';

    const parts = dateString.split('-').map(Number);
    if (
      parts.length !== 3 ||
      parts.some(part => !Number.isFinite(part)) ||
      !parts[0] || !parts[1] || !parts[2]
    ) {
      return '—';
    }

    const date = new Date(parts[0], parts[1] - 1, parts[2]);

    return date.toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric'
    });
  }

  function followUpLabel(lead) {
    const value = String(lead.follow_up_date || '').slice(0, 10);
    if (!value) return 'Not scheduled';

    const stats = getFollowUpStats([lead]);

    if (isConverted(lead)) return `${formatDate(value)} · Converted`;
    if (stats.overdue) return `${formatDate(value)} · Overdue`;
    if (stats.today) return `${formatDate(value)} · Due today`;

    return formatDate(value);
  }

  function showLogin(message = '') {
    isAuthenticated = false;
    loginScreen.hidden = false;
    dashboard.hidden = true;
    if (loginError) loginError.textContent = message;
  }

  function showDashboard() {
    isAuthenticated = true;
    loginScreen.hidden = true;
    dashboard.hidden = false;
    if (loginError) loginError.textContent = '';
  }

  async function api(path, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');

    if (options.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    if (csrfToken && ['POST', 'PATCH', 'PUT', 'DELETE'].includes(method)) {
      headers.set('X-CSRF-Token', csrfToken);
    }

    let response;

    try {
      response = await fetch(`${API}${path}`, {
        ...options,
        method,
        headers,
        credentials: 'include'
      });
    } catch {
      throw new Error(
        'Cannot connect to Flask. Check that the backend is running.'
      );
    }

    const data = await response.json().catch(() => ({}));

    if (response.status === 401) {
      if (isAuthenticated) {
        showLogin('Session expired. Please sign in again.');
      }
      throw new Error(data.error || 'Authentication required.');
    }

    if (!response.ok) {
      throw new Error(data.error || `Request failed (${response.status}).`);
    }

    return data;
  }

  async function getCsrfToken() {
    const data = await api('/auth/csrf');

    if (!data.csrf_token) {
      throw new Error('CSRF token missing.');
    }

    csrfToken = data.csrf_token;
  }

  async function loadLeads() {
    const result = await api('/leads');
    const receivedLeads = Array.isArray(result) ? result : result.leads;

    if (!Array.isArray(receivedLeads)) {
      throw new Error('Unexpected leads response from the backend.');
    }

    leads = receivedLeads;
    renderLeads();
    await refreshAnalytics();
  }

  function renderLeads() {
    const total = leads.length;

    const qualified = leads.filter(
      lead => String(lead.status).toLowerCase() === 'qualified'
    ).length;

    const followUps = getFollowUpStats();

    setText('#leadCount', total);
    setText('#totalKpi', total);
    setText('#qualifiedKpi', qualified);
    setText('#analyticsTotal', total);
    setText(
      '#analyticsQualified',
      total ? `${Math.round(qualified / total * 100)}%` : '0%'
    );

    setText('#followUpsDueKpi', followUps.due);
    setText('#analyticsFollowUpsDue', followUps.due);

    setText(
      '#followUpsDueNote',
      `${followUps.overdue} overdue · ${followUps.today} due today`
    );

    setText(
      '#analyticsFollowUpsNote',
      `${followUps.overdue} overdue · ${followUps.today} due today · ${followUps.upcoming} upcoming`
    );

    const connection = $('#connectionPill');
    if (connection) connection.textContent = '● DATABASE CONNECTED';

    const rowHTML = (lead, recent = false) => {
      const id = Number(lead.id);
      const name = escapeHTML(lead.name);
      const email = escapeHTML(lead.email);
      const company = escapeHTML(lead.company);
      const source = escapeHTML(lead.source || 'Unknown');
      const status = escapeHTML(lead.status || 'New');
      const addedDate = escapeHTML(
        lead.created_at ? String(lead.created_at).slice(0, 10) : '—'
      );
      const followUp = escapeHTML(followUpLabel(lead));

      if (recent) {
        return `
          <tr>
            <td><b>${name}</b><br><small>${email}</small></td>
            <td>${source}</td>
            <td>${status}</td>
            <td>${followUp}</td>
            <td>${addedDate}</td>
            <td></td>
          </tr>`;
      }

      return `
        <tr>
          <td><b>${name}</b><br><small>${email}</small></td>
          <td>${company}</td>
          <td>${source}</td>
          <td>${status}</td>
          <td>${followUp}</td>
          <td>${addedDate}</td>
          <td>
            <button type="button" class="btn btn-outline"
              data-edit-lead="${id}">Edit</button>
            <button type="button" class="btn btn-outline"
              data-delete-lead="${id}">Delete</button>
          </td>
        </tr>`;
    };

    const allBody = $('#allBody');

    if (allBody) {
      const query = ($('#search')?.value || '').trim().toLowerCase();
      const filter = $('#filter')?.value || 'all';

      const filtered = leads.filter(lead => {
        const searchable = [
          lead.name,
          lead.email,
          lead.company,
          lead.source,
          lead.service,
          lead.requirement,
          lead.follow_up_date,
          lead.status
        ].join(' ').toLowerCase();

        return searchable.includes(query) &&
          (
            filter === 'all' ||
            String(lead.status || '').toLowerCase() ===
              String(filter).toLowerCase()
          );
      });

      allBody.innerHTML = filtered.length
        ? filtered.map(lead => rowHTML(lead)).join('')
        : '<tr><td colspan="7">No matching leads found.</td></tr>';

      setText('#resultCount', `${filtered.length} leads`);
    }

    const recentBody = $('#recentBody');

    if (recentBody) {
      const recentLeads = [...leads]
        .sort((a, b) =>
          String(b.created_at || '').localeCompare(String(a.created_at || ''))
        )
        .slice(0, 5);

      recentBody.innerHTML = recentLeads.length
        ? recentLeads.map(lead => rowHTML(lead, true)).join('')
        : '<tr><td colspan="6">No saved leads yet.</td></tr>';
    }

    renderSourcesFromLeads();
    renderStatusesFromLeads();
  }

  function renderSourcesFromLeads() {
    const counts = {};

    leads.forEach(lead => {
      const source = String(lead.source || '').trim() || 'Unknown';
      counts[source] = (counts[source] || 0) + 1;
    });

    const sources = Object.entries(counts).map(([source, count]) => ({
      source,
      count
    }));

    renderSourceLegend(sources);
    renderDonut(sources.map(item => item.count));
    setText('#sourceTotal', leads.length);
  }

  function renderStatusesFromLeads() {
    const counts = {};

    leads.forEach(lead => {
      const status = String(lead.status || '').trim() || 'Unknown';
      counts[status] = (counts[status] || 0) + 1;
    });

    renderStatusBreakdown(
      Object.entries(counts).map(([status, count]) => ({ status, count }))
    );
  }

  function renderSourceLegend(sources) {
    const legend = $('#sourceLegend');
    if (!legend) return;

    const valid = Array.isArray(sources)
      ? sources.filter(item => Number(item.count) > 0)
      : [];

    legend.innerHTML = valid.length
      ? valid.map(item => `
          <p>${escapeHTML(item.source ?? item.name ?? 'Unknown')}
            <b>${Number(item.count) || 0}</b>
          </p>
        `).join('')
      : '<p>No saved lead sources yet.</p>';
  }

  function renderDonut(values) {
    const donut = $('#sourceDonut');
    if (!donut) return;

    const palette = [
      '#d6b46a',
      '#f0dca3',
      '#9d8248',
      '#ffffff',
      '#78633a',
      '#b9b5a9',
      '#55472d'
    ];

    const numbers = values.map(value => Math.max(0, Number(value) || 0));
    const total = numbers.reduce((sum, value) => sum + value, 0);

    if (!total) {
      donut.style.background = 'conic-gradient(#25251f 0deg 360deg)';
      donut.setAttribute('title', 'No lead source data');
      return;
    }

    let current = 0;

    const stops = numbers.map((value, index) => {
      const start = current;
      current += value / total * 360;
      return `${palette[index % palette.length]} ${start}deg ${current}deg`;
    });

    donut.style.background = `conic-gradient(${stops.join(', ')})`;
    donut.setAttribute('title', `${total} leads across all sources`);
  }

  function renderStatusBreakdown(statuses) {
    const breakdown = $('#statusBreakdown');
    if (!breakdown) return;

    const valid = Array.isArray(statuses)
      ? statuses.filter(item => Number(item.count) > 0)
      : [];

    breakdown.innerHTML = valid.length
      ? valid.map(item => `
          <p>${escapeHTML(item.status || 'Unknown')}:
            <b>${Number(item.count) || 0}</b>
          </p>
        `).join('')
      : '<p>No saved leads yet.</p>';
  }

  function formatAxisDate(dateString) {
    const parts = String(dateString || '').split('-').map(Number);

    if (
      parts.length !== 3 ||
      parts.some(part => !Number.isFinite(part))
    ) {
      return '—';
    }

    const date = new Date(parts[0], parts[1] - 1, parts[2]);

    return date.toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short'
    });
  }

  function aggregateDays(rows, bucketCount = 7) {
    const buckets = Array.from({ length: bucketCount }, () => ({
      total: 0,
      qualified: 0,
      firstDate: '',
      lastDate: ''
    }));

    if (!Array.isArray(rows) || rows.length === 0) return buckets;

    rows.forEach((row, index) => {
      const bucketIndex = Math.min(
        bucketCount - 1,
        Math.floor(index * bucketCount / rows.length)
      );

      const bucket = buckets[bucketIndex];

      bucket.total += Number(row.total) || 0;
      bucket.qualified += Number(row.qualified) || 0;

      if (!bucket.firstDate) bucket.firstDate = row.date || '';
      bucket.lastDate = row.date || '';
    });

    return buckets;
  }

  function renderChart(chartSelector, axisSelector, rows) {
    const chart = $(chartSelector);
    const axis = $(axisSelector);

    if (!chart) return;

    const buckets = aggregateDays(rows, 7);
    const maxValue = Math.max(
      1,
      ...buckets.map(bucket =>
        Math.max(bucket.total, bucket.qualified)
      )
    );

    chart.innerHTML = buckets.map(bucket => {
      const totalHeight = bucket.total
        ? Math.max(3, bucket.total / maxValue * 100)
        : 0;

      const qualifiedHeight = bucket.qualified
        ? Math.max(3, bucket.qualified / maxValue * 100)
        : 0;

      const label = bucket.firstDate
        ? `${formatAxisDate(bucket.firstDate)} – ${formatAxisDate(bucket.lastDate)}`
        : 'No data';

      return `
        <div title="${escapeHTML(label)}">
          <i title="Total leads: ${bucket.total}"
             style="height:${totalHeight}%"></i>
          <i title="Qualified leads: ${bucket.qualified}"
             style="height:${qualifiedHeight}%"></i>
        </div>`;
    }).join('');

    if (axis) {
      const labels = buckets.map(bucket =>
        bucket.firstDate ? formatAxisDate(bucket.firstDate) : '—'
      );

      const spans = [...axis.querySelectorAll('span')];

      if (spans.length) {
        spans.forEach((span, index) => {
          span.textContent = labels[index] || '';
        });
      } else {
        axis.innerHTML = labels.map(label =>
          `<span>${escapeHTML(label)}</span>`
        ).join('');
      }
    }
  }

  async function loadAnalytics(days, chartSelector, axisSelector, totalSelector) {
    const data = await api(
      `/analytics?days=${encodeURIComponent(days)}`
    );

    if (!data || !Array.isArray(data.daily)) {
      throw new Error('Unexpected analytics response from the backend.');
    }

    renderChart(chartSelector, axisSelector, data.daily);

    const periodTotal = data.daily.reduce(
      (sum, row) => sum + (Number(row.total) || 0),
      0
    );

    setText(totalSelector, periodTotal);
    return data;
  }

  async function refreshAnalytics() {
    if (!isAuthenticated) return;

    const requestId = ++analyticsRequestId;
    const overviewDays = Number($('#range')?.value) || 7;
    const analyticsDays = Number($('#analyticsRange')?.value) || 7;

    try {
      const [overviewData, analyticsData] = await Promise.all([
        loadAnalytics(
          overviewDays,
          '#barChart',
          '#chartAxis',
          '#chartTotal'
        ),
        loadAnalytics(
          analyticsDays,
          '#analyticsBarChart',
          '#analyticsChartAxis',
          '#analyticsChartTotal'
        )
      ]);

      if (requestId !== analyticsRequestId) return;

      setText('#analyticsTotal', Number(analyticsData.total) || 0);

      const rate = Number(analyticsData.qualification_rate) || 0;
      setText('#analyticsQualified', `${Math.round(rate)}%`);

      // Counts come from the backend database.
      const due = Number(analyticsData.follow_ups_due) || 0;
      const overdue = Number(analyticsData.overdue_follow_ups) || 0;
      const dueToday = Number(analyticsData.today_follow_ups) || 0;
      const upcoming = Number(analyticsData.upcoming_follow_ups) || 0;

      setText('#followUpsDueKpi', due);
      setText('#analyticsFollowUpsDue', due);
      setText('#followUpsDueNote', `${overdue} overdue · ${dueToday} due today`);
      setText(
        '#analyticsFollowUpsNote',
        `${overdue} overdue · ${dueToday} due today · ${upcoming} upcoming`
      );

      if (Array.isArray(analyticsData.sources)) {
        const sources = analyticsData.sources.map(item => ({
          source: item.source || 'Unknown',
          count: Number(item.count) || 0
        }));

        renderSourceLegend(sources);
        renderDonut(sources.map(item => item.count));

        setText(
          '#sourceTotal',
          sources.reduce((sum, item) => sum + item.count, 0)
        );
      }

      if (Array.isArray(analyticsData.statuses)) {
        renderStatusBreakdown(analyticsData.statuses);
      }

      const overviewTotal = overviewData.daily.reduce(
        (sum, row) => sum + (Number(row.total) || 0),
        0
      );

      setText('#chartTotal', overviewTotal);
    } catch (error) {
      console.error('Nexora analytics error:', error.message);
    }
  }

  function openLeadModal(lead = null) {
    if (!leadModal || !leadForm) {
      alert('Lead form not found. Check dashboard.html.');
      return;
    }

    leadForm.reset();

    $('#leadId').value = lead ? lead.id : '';
    $('#modalTitle').textContent = lead ? 'Edit lead' : 'Add a lead';

    $('#name').value = lead?.name || '';
    $('#email').value = lead?.email || '';
    $('#company').value = lead?.company || '';
    $('#service').value = lead?.service || '';
    $('#requirement').value = lead?.requirement || '';
    $('#followUpDate').value = String(lead?.follow_up_date || '').slice(0, 10);
    $('#source').value = lead?.source || 'Website';
    $('#status').value = lead?.status || 'New';

    if (typeof leadModal.showModal === 'function') {
      if (!leadModal.open) leadModal.showModal();
    } else {
      leadModal.setAttribute('open', '');
    }
  }

  function closeLeadModal() {
    if (leadModal?.open) {
      leadModal.close();
    } else {
      leadModal?.removeAttribute('open');
    }
  }

  $('#allBody')?.addEventListener('click', async event => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const editButton = target.closest('[data-edit-lead]');
    const deleteButton = target.closest('[data-delete-lead]');

    if (editButton) {
      const id = Number(editButton.dataset.editLead);
      const lead = leads.find(item => Number(item.id) === id);
      if (lead) openLeadModal(lead);
      return;
    }

    if (deleteButton) {
      const id = Number(deleteButton.dataset.deleteLead);
      const lead = leads.find(item => Number(item.id) === id);
      if (!lead) return;

      if (!confirm(`Delete lead "${lead.name}" permanently?`)) return;

      deleteButton.disabled = true;

      try {
        await api(`/leads/${id}`, { method: 'DELETE' });
        await loadLeads();
        alert('Lead deleted successfully.');
      } catch (error) {
        alert(`Delete failed: ${error.message}`);
        deleteButton.disabled = false;
      }
    }
  });

  async function handleLogin(event) {
    event.preventDefault();

    if (loginButton) {
      loginButton.disabled = true;
      loginButton.textContent = 'Signing in...';
    }

    try {
      await getCsrfToken();

      const data = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          email: emailInput.value.trim(),
          password: passwordInput.value
        })
      });

      if (data.csrf_token) csrfToken = data.csrf_token;
      passwordInput.value = '';

      const session = await api('/auth/me');

      if (session.authenticated === false) {
        throw new Error('Login session could not be verified.');
      }

      if (session.csrf_token) csrfToken = session.csrf_token;

      showDashboard();
      await loadLeads();
    } catch (error) {
      showLogin(error.message);
      console.error('Nexora login/data error:', error);
    } finally {
      if (loginButton) {
        loginButton.disabled = false;
        loginButton.textContent = 'Sign in securely';
      }
    }
  }

  async function handleLogout() {
    try {
      if (csrfToken) {
        await api('/auth/logout', { method: 'POST' });
      }
    } catch (error) {
      console.error('Logout error:', error.message);
    }

    csrfToken = '';
    showLogin('You have been signed out.');
  }

  loginForm.addEventListener('submit', handleLogin);
  logoutButton?.addEventListener('click', handleLogout);

  $('#addLead')?.addEventListener('click', () => openLeadModal());
  $('#addLeadTop')?.addEventListener('click', () => openLeadModal());
  $('#closeModal')?.addEventListener('click', closeLeadModal);
  $('#cancelModal')?.addEventListener('click', closeLeadModal);

  leadForm?.addEventListener('submit', async event => {
    event.preventDefault();

    const saveButton = leadForm.querySelector(
      'button[type="submit"], button:not([type])'
    );

    const payload = {
      name: $('#name').value.trim(),
      email: $('#email').value.trim(),
      company: $('#company').value.trim(),
      service: $('#service').value.trim(),
      requirement: $('#requirement').value.trim(),
      follow_up_date: $('#followUpDate').value,
      source: $('#source').value,
      status: $('#status').value
    };

    if (!payload.name || !payload.email || !payload.company) {
      alert('Name, email and company are required.');
      return;
    }

    const id = $('#leadId').value;
    const wasEditing = Boolean(id);

    if (saveButton) {
      saveButton.disabled = true;
      saveButton.textContent = 'Saving...';
    }

    try {
      if (wasEditing) {
        await api(`/leads/${Number(id)}`, {
          method: 'PATCH',
          body: JSON.stringify(payload)
        });
      } else {
        await api('/leads', {
          method: 'POST',
          body: JSON.stringify(payload)
        });

        // Public lead creation starts with no follow-up date.
        // If a date was selected, update the newly created lead using its ID.
        // The response contains the newly created record.
      }

      if (!wasEditing && payload.follow_up_date) {
        // The public endpoint returns the new lead's database ID.
        // Fetching the lead list lets us locate that new record safely.
        const refreshed = await api('/leads');
        const created = Array.isArray(refreshed)
          ? refreshed.find(lead =>
              lead.email === payload.email &&
              lead.company === payload.company &&
              !lead.follow_up_date
            )
          : null;

        if (created) {
          await api(`/leads/${Number(created.id)}`, {
            method: 'PATCH',
            body: JSON.stringify({
              follow_up_date: payload.follow_up_date
            })
          });
        }
      }

      closeLeadModal();
      await loadLeads();

      alert(
        wasEditing
          ? 'Lead updated successfully.'
          : 'Lead saved successfully.'
      );
    } catch (error) {
      alert(`Could not save lead: ${error.message}`);
      console.error('Nexora save lead error:', error);
    } finally {
      if (saveButton) {
        saveButton.disabled = false;
        saveButton.textContent = 'Save lead';
      }
    }
  });

  $('#search')?.addEventListener('input', renderLeads);
  $('#filter')?.addEventListener('change', renderLeads);

  $('#range')?.addEventListener('change', refreshAnalytics);
  $('#analyticsRange')?.addEventListener('change', refreshAnalytics);

  $('#export')?.addEventListener('click', () => {
    const rows = [
      [
        'Name',
        'Email',
        'Company',
        'Service',
        'Requirement',
        'Source',
        'Status',
        'Follow-up date',
        'Created'
      ],
      ...leads.map(lead => [
        lead.name,
        lead.email,
        lead.company,
        lead.service,
        lead.requirement,
        lead.source,
        lead.status,
        lead.follow_up_date,
        lead.created_at
      ])
    ];

    const csv = rows.map(row => row.map(value =>
      `"${String(value ?? '').replace(/"/g, '""')}"`
    ).join(',')).join('\r\n');

    const url = URL.createObjectURL(
      new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    );

    const link = document.createElement('a');
    link.href = url;
    link.download = 'nexora-leads.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();

    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  $$('[data-view]').forEach(button => {
    button.addEventListener('click', () => {
      const view = button.dataset.view;

      $$('.view').forEach(section => {
        section.classList.toggle('active', section.id === `view-${view}`);
      });

      $$('[data-view]').forEach(item => {
        item.classList.toggle('active', item === button);
      });

      const crumb = $('#crumbCurrent');

      if (crumb) {
        crumb.textContent =
          button.querySelector('span')?.textContent || view;
      }

      $('#sidebar')?.classList.remove('open');
      $('#backdrop')?.classList.remove('open');
    });
  });

  $$('[data-goto]').forEach(button => {
    button.addEventListener('click', () => {
      const target = $(`[data-view="${button.dataset.goto}"]`);
      target?.click();
    });
  });

  $('#sideToggle')?.addEventListener('click', () => {
    $('#sidebar')?.classList.toggle('open');
    $('#backdrop')?.classList.toggle('open');
  });

  $('#backdrop')?.addEventListener('click', () => {
    $('#sidebar')?.classList.remove('open');
    $('#backdrop')?.classList.remove('open');
  });

  $('#dismissNotice')?.addEventListener('click', () => {
    $('#notice')?.remove();
  });

  $('#notifications')?.addEventListener('click', () => {
    const stats = getFollowUpStats();

    alert(
      `Follow-up summary\n\n` +
      `Overdue: ${stats.overdue}\n` +
      `Due today: ${stats.today}\n` +
      `Upcoming: ${stats.upcoming}`
    );
  });

  window.NexoraAPI = {
    get: path => api(path),
    post: (path, body) => api(path, {
      method: 'POST',
      body: JSON.stringify(body)
    }),
    patch: (path, body) => api(path, {
      method: 'PATCH',
      body: JSON.stringify(body)
    }),
    delete: path => api(path, { method: 'DELETE' }),
    logout: handleLogout,
    isAuthenticated: () => isAuthenticated,
    refreshLeads: loadLeads,
    refreshAnalytics
  };

  showLogin();

  (async () => {
    try {
      await getCsrfToken();

      const session = await api('/auth/me');

      if (session.authenticated) {
        if (session.csrf_token) csrfToken = session.csrf_token;
        showDashboard();
        await loadLeads();
      }
    } catch (error) {
      console.error('Nexora startup:', error.message);
      showLogin();
    }
  })();
});
