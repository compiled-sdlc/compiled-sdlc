package org.springframework.samples.petclinic.customers.web;

import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.customers.model.Owner;
import org.springframework.samples.petclinic.customers.model.OwnerRepository;
import org.springframework.samples.petclinic.customers.web.mapper.OwnerEntityMapper;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-110: the owner list is bounded, by default and on request,
 * and is still the array every caller reads.
 *
 * The repository is stubbed on both routes an implementation might take --- the whole
 * list, or a page of it --- so the check tests the bound the caller sees rather than
 * the way it was arrived at.
 */
@WebMvcTest(OwnerResource.class)
@ActiveProfiles("test")
class OwnerListBoundAcceptanceTest {

    private static final int TOTAL = 50;

    @Autowired
    MockMvc mvc;

    @MockitoBean
    OwnerRepository ownerRepository;

    @MockitoBean
    OwnerEntityMapper ownerEntityMapper;

    private Owner anOwner(int index) {
        Owner owner = new Owner();
        owner.setFirstName("George");
        owner.setLastName(String.format("Owner-%02d", index));
        owner.setAddress("110 W. Liberty St.");
        owner.setCity("Madison");
        owner.setTelephone("6085551023");
        return owner;
    }

    private List<Owner> owners() {
        List<Owner> all = new ArrayList<>();
        for (int index = 0; index < TOTAL; index++) {
            all.add(anOwner(index));
        }
        return all;
    }

    /** Stub the whole list and any page of it, so either implementation answers. */
    private void givenTheTableHolds(List<Owner> all) {
        given(ownerRepository.findAll()).willReturn(all);
        given(ownerRepository.findAll(any(Pageable.class))).willAnswer(invocation -> {
            Pageable pageable = invocation.getArgument(0);
            int from = Math.min((int) pageable.getOffset(), all.size());
            int to = Math.min(from + pageable.getPageSize(), all.size());
            return new PageImpl<>(all.subList(from, to), pageable, all.size());
        });
    }

    @Test
    void shouldAnswerTheFirstTwentyWhenNothingIsAsked() throws Exception {
        givenTheTableHolds(owners());

        mvc.perform(get("/owners").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(20))
            .andExpect(jsonPath("$[0].lastName").value("Owner-00"));
    }

    @Test
    void shouldAnswerThePageTheCallerAsksFor() throws Exception {
        givenTheTableHolds(owners());

        mvc.perform(get("/owners?page=2&size=5").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(5))
            .andExpect(jsonPath("$[0].lastName").value("Owner-10"));
    }

    @Test
    void shouldRefuseAPageSizeOverTheCeilingWithoutQuerying() throws Exception {
        mvc.perform(get("/owners?size=101").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isBadRequest());

        verify(ownerRepository, never()).findAll();
        verify(ownerRepository, never()).findAll(any(Pageable.class));
    }

    @Test
    void shouldReportTheTotalBesideTheAnswer() throws Exception {
        givenTheTableHolds(owners());

        mvc.perform(get("/owners").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(header().string("X-Total-Count", String.valueOf(TOTAL)));
    }

    @Test
    void shouldStillBeAnArrayOfOwnersWithEveryFieldItCarried() throws Exception {
        givenTheTableHolds(List.of(anOwner(0)));

        mvc.perform(get("/owners").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$").isArray())
            .andExpect(jsonPath("$[0].firstName").value("George"))
            .andExpect(jsonPath("$[0].lastName").value("Owner-00"))
            .andExpect(jsonPath("$[0].address").value("110 W. Liberty St."))
            .andExpect(jsonPath("$[0].city").value("Madison"))
            .andExpect(jsonPath("$[0].telephone").value("6085551023"));
    }
}
